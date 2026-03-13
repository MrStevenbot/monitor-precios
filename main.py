import subprocess
import sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "schedule", "beautifulsoup4", "lxml", "pyTelegramBotAPI"])

import requests
import json
import time
import schedule
import os
from datetime import datetime
from bs4 import BeautifulSoup
import threading
import telebot

# ─── CONFIGURACIÓN ───────────────────────────────────────────
TELEGRAM_TOKEN = "8754880187:AAHojj4MMgZRKT0XaOnTVsb8QBiqDP7Kzbo"
CHAT_ID = "8428923831"
PRECIO_HISTORIAL_FILE = "historial_precios.json"
UMBRAL_OFERTA = 20
UMBRAL_ERROR = 40

BOT_PAUSADO = False
ULTIMO_ESCANEO = None

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
}

BUSQUEDAS = [
    "notebook", "smartphone", "televisor", "tablet", "iphone",
    "samsung galaxy", "consola videojuegos", "camara fotografica",
    "auriculares", "smartwatch", "parlante bluetooth", "drone",
    "refrigerador", "lavadora", "microondas", "aire acondicionado",
    "aspiradora", "cafetera", "bicicleta", "bicicleta electrica",
    "zapatillas running", "zapatillas nike", "zapatillas adidas",
    "trotadora", "pesas", "chaqueta", "poleron", "jeans", "vestido",
    "ropa deportiva", "perfume hombre", "perfume mujer", "crema facial",
    "maquillaje", "sofa", "escritorio", "silla gamer", "colchon",
    "lampara", "taladro", "set herramientas", "lego", "juguete niños",
    "alimento perro", "alimento gato", "accesorios auto", "casco moto",
]
# ─────────────────────────────────────────────────────────────


def enviar_telegram(mensaje, foto_url=None):
    try:
        if foto_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            payload = {"chat_id": CHAT_ID, "photo": foto_url, "caption": mensaje, "parse_mode": "HTML"}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error Telegram: {e}")
        return False


def cargar_historial():
    if os.path.exists(PRECIO_HISTORIAL_FILE):
        with open(PRECIO_HISTORIAL_FILE, "r") as f:
            return json.load(f)
    return {}


def guardar_historial(historial):
    with open(PRECIO_HISTORIAL_FILE, "w") as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)


def calcular_variacion(precio_actual, precio_anterior):
    if precio_anterior == 0:
        return 0
    return ((precio_anterior - precio_actual) / precio_anterior) * 100


def evaluar_y_alertar(productos, historial):
    alertas = []
    for p in productos:
        item_id = p.get('id', '')
        titulo = p.get('title', 'Sin título')
        precio_actual = float(p.get('price', 0))
        precio_original = float(p.get('original_price') or precio_actual)
        link = p.get('permalink', '')
        foto_url = p.get('thumbnail', '')
        tienda = p.get('tienda', '')
        descuento_nativo = float(p.get('discount_percentage', 0))

        if not precio_actual:
            continue

        # Descuento del vendedor (precio original vs actual)
        descuento_vendedor = calcular_variacion(precio_actual, precio_original)

        # Variación histórica (precio anterior vs actual)
        precio_anterior = historial.get(item_id, {}).get('precio', 0)
        variacion_historica = calcular_variacion(precio_actual, precio_anterior) if precio_anterior > 0 else 0

        # Usar el mayor descuento detectado
        porcentaje = max(descuento_vendedor, variacion_historica, descuento_nativo)

        # Verificar si ya fue alertado con este precio para evitar spam
        ya_alertado = historial.get(item_id, {}).get('precio_alertado', 0)
        ya_fue_alertado = ya_alertado == precio_actual

        # Actualizar historial
        historial[item_id] = {
            'precio': precio_actual,
            'titulo': titulo,
            'ultima_vez': datetime.now().isoformat(),
            'precio_alertado': historial.get(item_id, {}).get('precio_alertado', 0)
        }

        # Solo alertar si supera umbral Y no fue alertado con este mismo precio
        if not ya_fue_alertado:
            if porcentaje >= UMBRAL_ERROR:
                tipo = '🚨 POSIBLE ERROR DE PRECIO\n🏪 Tienda: ' + tienda
                alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url))
                historial[item_id]['precio_alertado'] = precio_actual
            elif porcentaje >= UMBRAL_OFERTA:
                tipo = '🔥 OFERTA DETECTADA\n🏪 Tienda: ' + tienda
                alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url))
                historial[item_id]['precio_alertado'] = precio_actual

    return alertas, historial


def formatear_alerta(tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url=None):
    return (
        f"{tipo}\n\n"
        f"📦 <b>{titulo}</b>\n"
        f"💰 Precio actual: <b>${precio_actual:,.0f} CLP</b>\n"
        f"📊 Precio anterior: ${precio_original:,.0f} CLP\n"
        f"📉 Descuento: <b>{porcentaje:.1f}%</b>\n"
        f"🔗 {link}"
    )


def enviar_alertas(alertas, nombre_tienda, total_alertas):
    for alerta in alertas:
        mensaje = formatear_alerta(*alerta)
        enviado = enviar_telegram(mensaje, foto_url=alerta[7] if len(alerta) > 7 else None)
        if enviado:
            print(f"  ✅ {nombre_tienda}: {alerta[1][:50]}...")
            total_alertas += 1
        time.sleep(1)
    return total_alertas


# ─── MERCADOLIBRE ────────────────────────────────────────────
def buscar_mercadolibre(query):
    url = "https://api.mercadolibre.com/sites/MLC/search"
    params = {"q": query, "limit": 50, "sort": "price_asc"}
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        resultados = []
        for p in data.get("results", []):
            resultados.append({
                'id': 'ml_' + str(p.get('id', '')),
                'title': p.get('title', ''),
                'price': p.get('price', 0),
                'original_price': p.get('original_price') or p.get('price', 0),
                'permalink': p.get('permalink', ''),
                'thumbnail': p.get('thumbnail', '').replace('I.jpg', 'O.jpg'),
                'tienda': 'MercadoLibre.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error MercadoLibre ({query}): {e}")
        return []


# ─── RIPLEY ──────────────────────────────────────────────────
def buscar_ripley(query):
    url = f'https://simple.ripley.cl/api/search?query={query}&sort=priceAsc&page=1&limit=50'
    headers_ripley = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-CL,es;q=0.9',
        'Referer': 'https://simple.ripley.cl/search/notebook',
        'Origin': 'https://simple.ripley.cl',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
    }
    try:
        response = requests.get(url, headers=headers_ripley, timeout=15)
        data = response.json()
        resultados = []
        for p in data.get('products', [])[:50]:
            precios = p.get('prices', {})
            precio_actual = precios.get('offerPrice') or precios.get('listPrice', 0)
            precio_original = precios.get('listPrice') or precio_actual
            if not precio_actual:
                continue
            resultados.append({
                'id': 'rip_' + str(p.get('partNumber', '')),
                'title': p.get('name', ''),
                'price': float(precio_actual),
                'original_price': float(precio_original),
                'discount_percentage': float(precios.get('discountPercentage', 0)),
                'permalink': p.get('url', ''),
                'thumbnail': p.get('fullImage', p.get('thumbnail', '')),
                'tienda': 'Ripley.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error Ripley ({query}): {e}")
        return []


# ─── FALABELLA ───────────────────────────────────────────────
def buscar_falabella(query):
    url = f'https://www.falabella.com/s/browse/v1/listing/cl?zone=13&currentPage=1&resultsPerPage=50&query={query}'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        data = response.json()
        resultados = []
        for p in data.get('data', {}).get('results', []):
            precio_actual = 0
            precio_original = 0
            for precio in p.get('prices', []):
                val = str(precio.get('price', ['0'])[0]).replace('.', '').replace(',', '')
                if precio.get('label') == 'Precio Falabella.com':
                    precio_actual = float(val) if val.isdigit() else 0
                if precio.get('label') == 'Precio Normal':
                    precio_original = float(val) if val.isdigit() else 0
            if not precio_actual:
                continue
            resultados.append({
                'id': 'fal_' + str(p.get('id', '')),
                'title': p.get('displayName', ''),
                'price': precio_actual,
                'original_price': precio_original or precio_actual,
                'permalink': 'https://www.falabella.com' + p.get('url', ''),
                'thumbnail': p.get('mediaUrls', [''])[0] if p.get('mediaUrls') else '',
                'tienda': 'Falabella.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error Falabella ({query}): {e}")
        return []


# ─── PARIS ───────────────────────────────────────────────────
def buscar_paris(query):
    url = f'https://www.paris.cl/api/catalog_system/pub/products/search/{query}?O=OrderByPriceASC&_from=0&_to=49'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        data = response.json()
        resultados = []
        for p in data:
            items = p.get('items', [{}])
            if not items:
                continue
            sellers = items[0].get('sellers', [{}])
            if not sellers:
                continue
            precio_actual = sellers[0].get('commertialOffer', {}).get('Price', 0)
            precio_original = sellers[0].get('commertialOffer', {}).get('ListPrice', 0)
            imagen = items[0].get('images', [{}])[0].get('imageUrl', '') if items[0].get('images') else ''
            if not precio_actual:
                continue
            resultados.append({
                'id': 'par_' + str(p.get('productId', '')),
                'title': p.get('productName', ''),
                'price': float(precio_actual),
                'original_price': float(precio_original) or float(precio_actual),
                'permalink': 'https://www.paris.cl' + p.get('link', ''),
                'thumbnail': imagen,
                'tienda': 'Paris.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error Paris ({query}): {e}")
        return []


# ─── SODIMAC ─────────────────────────────────────────────────
def buscar_sodimac(query):
    url = f'https://www.sodimac.cl/sodimac-cl/search?Ntt={query}&sortBy=priceAsc&page=1'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        resultados = []
        productos = soup.select('[class*="product-card"]')[:50]
        for p in productos:
            titulo_el = p.select_one('[class*="title"]')
            precio_el = p.select_one('[class*="price-offer"]') or p.select_one('[class*="price"]')
            precio_orig_el = p.select_one('[class*="price-before"]')
            link_el = p.select_one('a')
            img_el = p.select_one('img')
            if not titulo_el or not precio_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            precio_str = precio_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '')
            precio_orig_str = precio_orig_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '') if precio_orig_el else precio_str
            try:
                precio_actual = float(''.join(filter(str.isdigit, precio_str)))
                precio_original = float(''.join(filter(str.isdigit, precio_orig_str)))
            except:
                continue
            if not precio_actual:
                continue
            link = 'https://www.sodimac.cl' + link_el['href'] if link_el and link_el.get('href') else ''
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'sod_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_original or precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'Sodimac.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error Sodimac ({query}): {e}")
        return []


# ─── HITES ───────────────────────────────────────────────────
# ─── LA POLAR ────────────────────────────────────────────────
def buscar_lapolar(query):
    url = f'https://www.lapolar.cl/search?q={query}&sort=price-asc&hitsPerPage=50'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        resultados = []
        productos = soup.select('[class*="product"]')[:50]
        for p in productos:
            titulo_el = p.select_one('[class*="name"]') or p.select_one('[class*="title"]')
            precio_el = p.select_one('[class*="price-special"]') or p.select_one('[class*="price"]')
            link_el = p.select_one('a')
            img_el = p.select_one('img')
            if not titulo_el or not precio_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            precio_str = precio_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '')
            try:
                precio_actual = float(''.join(filter(str.isdigit, precio_str)))
            except:
                continue
            if not precio_actual:
                continue
            link = 'https://www.lapolar.cl' + link_el['href'] if link_el and link_el.get('href') else ''
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'lap_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'LaPolar.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error LaPolar ({query}): {e}")
        return []


# ─── ABCDIN ──────────────────────────────────────────────────
def buscar_abcdin(query):
    url = f'https://www.abcdin.cl/search?q={query}&sort=price-asc&hitsPerPage=50'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        resultados = []
        productos = soup.select('[class*="product"]')[:50]
        for p in productos:
            titulo_el = p.select_one('[class*="name"]') or p.select_one('[class*="title"]')
            precio_el = p.select_one('[class*="price-special"]') or p.select_one('[class*="price"]')
            link_el = p.select_one('a')
            img_el = p.select_one('img')
            if not titulo_el or not precio_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            precio_str = precio_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '')
            try:
                precio_actual = float(''.join(filter(str.isdigit, precio_str)))
            except:
                continue
            if not precio_actual:
                continue
            link = 'https://www.abcdin.cl' + link_el['href'] if link_el and link_el.get('href') else ''
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'abc_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'AbcDin.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error AbcDin ({query}): {e}")
        return []



# ─── PC FACTORY ──────────────────────────────────────────────
def buscar_pcfactory(query):
    url = f'https://www.pcfactory.cl/buscar?q={query}&sort=price-asc'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        resultados = []
        productos = soup.select('[class*="product"]')[:50]
        for p in productos:
            titulo_el = p.select_one('[class*="name"]') or p.select_one('[class*="title"]')
            precio_el = p.select_one('[class*="price-offer"]') or p.select_one('[class*="price"]')
            precio_orig_el = p.select_one('[class*="price-before"]') or p.select_one('[class*="price-normal"]')
            link_el = p.select_one('a')
            img_el = p.select_one('img')
            if not titulo_el or not precio_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            precio_str = precio_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '')
            precio_orig_str = precio_orig_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '') if precio_orig_el else precio_str
            try:
                precio_actual = float(''.join(filter(str.isdigit, precio_str)))
                precio_original = float(''.join(filter(str.isdigit, precio_orig_str)))
            except:
                continue
            if not precio_actual:
                continue
            link = 'https://www.pcfactory.cl' + link_el['href'] if link_el and link_el.get('href') else ''
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'pcf_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_original or precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'PCFactory.cl'
            })
        return resultados
    except Exception as e:
        print(f'Error PCFactory ({query}): {e}')
        return []


# ─── LINIO ───────────────────────────────────────────────────
def buscar_linio(query):
    url = f'https://www.linio.cl/search?q={query}&sort_by=price&order=ASC&limit=50'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(response.text, 'lxml')
        resultados = []
        productos = soup.select('[class*="catalogue-product"]')[:50]
        for p in productos:
            titulo_el = p.select_one('[class*="product-title"]') or p.select_one('[class*="title"]')
            precio_el = p.select_one('[class*="price-main"]') or p.select_one('[class*="price"]')
            precio_orig_el = p.select_one('[class*="price-before"]')
            link_el = p.select_one('a')
            img_el = p.select_one('img')
            if not titulo_el or not precio_el:
                continue
            titulo = titulo_el.get_text(strip=True)
            precio_str = precio_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '')
            precio_orig_str = precio_orig_el.get_text(strip=True).replace('$', '').replace('.', '').replace(',', '') if precio_orig_el else precio_str
            try:
                precio_actual = float(''.join(filter(str.isdigit, precio_str)))
                precio_original = float(''.join(filter(str.isdigit, precio_orig_str)))
            except:
                continue
            if not precio_actual:
                continue
            link = link_el['href'] if link_el and link_el.get('href') else ''
            if link and not link.startswith('http'):
                link = 'https://www.linio.cl' + link
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'lin_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_original or precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'Linio.cl'
            })
        return resultados
    except Exception as e:
        print(f'Error Linio ({query}): {e}')
        return []

# ─── MOTOR PRINCIPAL ─────────────────────────────────────────
TIENDAS = [
    ('MercadoLibre', buscar_mercadolibre, BUSQUEDAS),           # API oficial
    ('Ripley',       buscar_ripley,       BUSQUEDAS[:15]),       # API corregida
    ('Falabella',    buscar_falabella,    BUSQUEDAS[:15]),       # API semi-oficial
]



# ─── COMANDOS TELEGRAM ───────────────────────────────────────
bot_telebot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot_telebot.message_handler(commands=['start'])
def cmd_start(message):
    bot_telebot.reply_to(message,
        "🤖 <b>Captador de Ofertas Chile</b>\n\n"
        "Comandos disponibles:\n"
        "/estado — Ver estado del bot\n"
        "/buscar [producto] — Buscar ahora\n"
        "/umbral [número] — Cambiar % mínimo oferta\n"
        "/error [número] — Cambiar % error de precio\n"
        "/pausa — Pausar alertas\n"
        "/activar — Reactivar alertas",
        parse_mode='HTML'
    )

@bot_telebot.message_handler(commands=['estado'])
def cmd_estado(message):
    global BOT_PAUSADO, ULTIMO_ESCANEO
    tiendas = ', '.join([t[0] for t in TIENDAS])
    historial = cargar_historial()
    estado = "⏸ PAUSADO" if BOT_PAUSADO else "✅ ACTIVO"
    ultimo = ULTIMO_ESCANEO.strftime('%H:%M:%S') if ULTIMO_ESCANEO else "Aún no"
    bot_telebot.reply_to(message,
        f"📊 <b>Estado del Bot</b>\n\n"
        f"🔘 Estado: {estado}\n"
        f"🏪 Tiendas: {tiendas}\n"
        f"📦 Productos en historial: {len(historial)}\n"
        f"🕐 Último escaneo: {ultimo}\n"
        f"⚙️ Umbral oferta: {UMBRAL_OFERTA}%\n"
        f"⚙️ Umbral error: {UMBRAL_ERROR}%",
        parse_mode='HTML'
    )

@bot_telebot.message_handler(commands=['buscar'])
def cmd_buscar(message):
    partes = message.text.split(maxsplit=1)
    if len(partes) < 2:
        bot_telebot.reply_to(message, "Uso: /buscar [producto]\nEjemplo: /buscar iphone")
        return
    query = partes[1]
    bot_telebot.reply_to(message, f"🔍 Buscando <b>{query}</b> ahora...", parse_mode='HTML')
    historial = cargar_historial()
    total = 0
    for nombre, funcion, _ in TIENDAS:
        productos = funcion(query)
        if not productos:
            continue
        alertas, historial = evaluar_y_alertar(productos, historial)
        total = enviar_alertas(alertas, nombre, total)
        time.sleep(1)
    guardar_historial(historial)
    if total == 0:
        bot_telebot.reply_to(message, f"Sin ofertas para <b>{query}</b> en este momento.", parse_mode='HTML')

@bot_telebot.message_handler(commands=['umbral'])
def cmd_umbral(message):
    global UMBRAL_OFERTA
    partes = message.text.split()
    if len(partes) < 2:
        bot_telebot.reply_to(message, f"Umbral oferta actual: {UMBRAL_OFERTA}%\nUso: /umbral [número]\nEjemplo: /umbral 15")
        return
    try:
        nuevo = int(partes[1])
        if nuevo < 5 or nuevo > 90:
            bot_telebot.reply_to(message, "El umbral debe estar entre 5 y 90.")
            return
        UMBRAL_OFERTA = nuevo
        bot_telebot.reply_to(message, f"✅ Umbral oferta: {UMBRAL_OFERTA}%\n🚨 Error de precio sigue en: {UMBRAL_ERROR}%")
    except:
        bot_telebot.reply_to(message, "Número inválido. Ejemplo: /umbral 15")

@bot_telebot.message_handler(commands=['error'])
def cmd_error(message):
    global UMBRAL_ERROR
    partes = message.text.split()
    if len(partes) < 2:
        bot_telebot.reply_to(message, f"Umbral error actual: {UMBRAL_ERROR}%\nUso: /error [número]\nEjemplo: /error 50")
        return
    try:
        nuevo = int(partes[1])
        if nuevo < 5 or nuevo > 90:
            bot_telebot.reply_to(message, "El umbral debe estar entre 5 y 90.")
            return
        UMBRAL_ERROR = nuevo
        bot_telebot.reply_to(message, f"✅ Umbral error de precio: {UMBRAL_ERROR}%\n🔥 Oferta sigue en: {UMBRAL_OFERTA}%")
    except:
        bot_telebot.reply_to(message, "Número inválido. Ejemplo: /error 50")

@bot_telebot.message_handler(commands=['pausa'])
def cmd_pausa(message):
    global BOT_PAUSADO
    BOT_PAUSADO = True
    bot_telebot.reply_to(message, "⏸ Bot pausado.\nUsa /activar para reanudar.")

@bot_telebot.message_handler(commands=['activar'])
def cmd_activar(message):
    global BOT_PAUSADO
    BOT_PAUSADO = False
    bot_telebot.reply_to(message, "▶️ Bot reactivado. Alertas automáticas activas.")
# ─────────────────────────────────────────────────────────────

def ejecutar_monitoreo():
    global BOT_PAUSADO, ULTIMO_ESCANEO
    if BOT_PAUSADO:
        print("Bot pausado, saltando ciclo.")
        return
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Iniciando monitoreo...")
    historial = cargar_historial()
    total_alertas = 0

    for nombre, funcion, categorias in TIENDAS:
        print(f"\n  🔍 Escaneando {nombre}...")
        for query in categorias:
            productos = funcion(query)
            if not productos:
                continue
            alertas, historial = evaluar_y_alertar(productos, historial)
            total_alertas = enviar_alertas(alertas, nombre, total_alertas)
            time.sleep(2)

    guardar_historial(historial)
    ULTIMO_ESCANEO = datetime.now()
    print(f"\n  ✅ Ciclo completado. Alertas enviadas: {total_alertas}")


def iniciar_bot_comandos():
    print("✅ Comandos Telegram activos")
    bot_telebot.infinity_polling()

def main():
    print("🤖 Monitor de Precios Chile iniciado")
    print(f"🏪 Tiendas: {', '.join([t[0] for t in TIENDAS])}")

    # Iniciar listener de comandos en hilo separado
    hilo_comandos = threading.Thread(target=iniciar_bot_comandos, daemon=True)
    hilo_comandos.start()

    enviar_telegram(
        "🤖 <b>Captador de Ofertas Chile activo</b>\n\n"
        "🏪 Tiendas: MercadoLibre, Ripley, Falabella\n"
        "📦 +1.500 artículos monitoreados\n"
        "🔄 Revisión cada 30 minutos\n\n"
        "Comandos: /estado /buscar /umbral /pausa /activar"
    )

    ejecutar_monitoreo()
    schedule.every(30).minutes.do(ejecutar_monitoreo)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
