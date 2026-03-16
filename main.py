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
bot_telebot = telebot.TeleBot(TELEGRAM_TOKEN)

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

@bot_telebot.message_handler(commands=['ofertas'])
def cmd_ofertas(message):
    historial = cargar_historial()
    if not historial:
        bot_telebot.reply_to(message, "Sin productos escaneados aun. Espera el primer ciclo.")
        return
    con_descuento = []
    for item_id, datos in historial.items():
        precio = datos.get('precio', 0)
        precio_original = datos.get('precio_original', 0)
        if precio_original > precio > 0:
            pct = ((precio_original - precio) / precio_original) * 100
            if pct >= UMBRAL_OFERTA:
                con_descuento.append((pct, datos.get('titulo', ''), precio, datos.get('link', '')))
    if not con_descuento:
        bot_telebot.reply_to(message, "Sin ofertas sobre " + str(UMBRAL_OFERTA) + "% en historial.")
        return
    con_descuento.sort(reverse=True)
    top = con_descuento[:10]
    lineas = ["<b>Top ofertas detectadas:</b>"]
    for i, (pct, titulo, precio, link) in enumerate(top, 1):
        lineas.append(str(i) + ". <b>" + titulo[:50] + "</b>")
        lineas.append("$" + f"{precio:,.0f}" + " CLP (" + f"{pct:.1f}" + "% OFF)")
        if link:
            lineas.append(link)
        lineas.append("")
    bot_telebot.reply_to(message, "\n".join(lineas), parse_mode='HTML')
# ─────────────────────────────────────────────────────────────


def enviar_telegram(mensaje, foto_url=None, silencioso=False):
    try:
        if foto_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            payload = {"chat_id": CHAT_ID, "photo": foto_url, "caption": mensaje, "parse_mode": "HTML", "disable_notification": silencioso}
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_notification": silencioso}
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        print(f"Error Telegram: {e}")
        return None

def fijar_mensaje(message_id):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/pinChatMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "message_id": message_id, "disable_notification": False}, timeout=10)
    except:
        pass

def enviar_alerta_error(titulo, precio_actual, precio_original, porcentaje, link, foto_url):
    alerta = (
        f"🚨🚨🚨 <b>¡¡POSIBLE ERROR DE PRECIO!!</b> 🚨🚨🚨\n\n"
        f"⚠️ <b>PRECIO ANORMALMENTE BAJO DETECTADO</b> ⚠️\n\n"
        f"📦 <b>{titulo}</b>\n"
        f"💰 Precio actual: <b>${precio_actual:,.0f} CLP</b>\n"
        f"📊 Precio anterior: ${precio_original:,.0f} CLP\n"
        f"📉 Descuento: <b>{porcentaje:.1f}%</b>\n"
        f"🔗 {link}\n\n"
        f"⚡ ¡COMPRA ANTES DE QUE LO CORRIJAN!"
    )
    resultado = enviar_telegram(alerta, foto_url=foto_url, silencioso=False)
    if resultado and resultado.get('result'):
        fijar_mensaje(resultado['result']['message_id'])
    time.sleep(5)
    enviar_telegram(f"🚨 <b>ALERTA:</b> {titulo[:60]}... — ${precio_actual:,.0f} CLP ({porcentaje:.1f}% OFF)\n🔗 {link}", silencioso=False)
    time.sleep(5)
    enviar_telegram(f"⚠️ ¿Ya lo compraste? Este precio puede ser un ERROR. Actúa rápido. 🔗 {link}", silencioso=False)


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
            'precio_original': precio_original,
            'titulo': titulo,
            'link': link,
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
        tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url = alerta
        if 'ERROR' in tipo:
            enviar_alerta_error(titulo, precio_actual, precio_original, porcentaje, link, foto_url)
            print(f"  🚨 ERROR PRECIO {nombre_tienda}: {titulo[:50]}...")
        else:
            mensaje = formatear_alerta(*alerta)
            resultado = enviar_telegram(mensaje, foto_url=foto_url)
            if resultado:
                print(f"  ✅ {nombre_tienda}: {titulo[:50]}...")
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



















# ─── MOTOR PRINCIPAL ─────────────────────────────────────────
# Tiendas para escaneo automático (IP USA - sin bloqueo)
TIENDAS = [
    ('MercadoLibre', buscar_mercadolibre, BUSQUEDAS),
    ('Falabella',    buscar_falabella,    BUSQUEDAS[:15]),
]

# Tiendas solo para búsqueda manual (requieren IP chilena)
TIENDAS_MANUAL = [
    ('MercadoLibre', buscar_mercadolibre, None),
    ('Falabella',    buscar_falabella,    None),
    ('Ripley',       buscar_ripley,       None),
    ('Paris',        buscar_paris,        None),
]

# ─── COMANDOS TELEGRAM ───────────────────────────────────────
@bot_telebot.message_handler(commands=['start'])
def cmd_start(message):
    bot_telebot.reply_to(message,
        "🇨🇱🔥 <b>CAPTADOR DE OFERTAS CHILE</b> 🔥🇨🇱\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👋 ¡Hola! Soy tu cazador de ofertas personal.\n"
        "Monitoreo tiendas chilenas 24/7 y te aviso al instante cuando hay un descuento que vale la pena.\n\n"
        "🚨 <b>Error de precio detectado</b> = triple alerta + mensaje fijado. Imposible perdérselo.\n\n"
        "🏪 MercadoLibre · Ripley · Falabella\n"
        "📦 +2.000 productos monitoreados\n"
        "⚡ Escaneo cada 30 minutos\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📲 <b>Comandos:</b>\n"
        "🔍 /buscar [producto]\n"
        "📊 /ofertas — top 10 descuentos\n"
        "📈 /estado — estado del bot\n"
        "⚙️ /umbral · /error · /pausa · /activar",
        parse_mode='HTML'
    )

@bot_telebot.message_handler(commands=['estado'])
def cmd_estado(message):
    global BOT_PAUSADO, ULTIMO_ESCANEO
    tiendas = ', '.join([t[0] for t in TIENDAS]) + " (auto)\nBúsqueda manual: " + ', '.join([t[0] for t in TIENDAS_MANUAL])
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
    total = 0
    for nombre, funcion, _ in TIENDAS:
        productos = funcion(query)
        if not productos:
            continue
        # En busqueda manual mostrar todo sin filtro de historial
        for p in productos:
            precio_actual = float(p.get('price', 0))
            precio_original = float(p.get('original_price') or precio_actual)
            descuento_nativo = float(p.get('discount_percentage', 0))
            descuento_vendedor = calcular_variacion(precio_actual, precio_original)
            porcentaje = max(descuento_vendedor, descuento_nativo)
            if porcentaje >= UMBRAL_ERROR:
                tipo = '🚨 POSIBLE ERROR DE PRECIO\n🏪 Tienda: ' + p.get('tienda', '')
                alerta = (tipo, p.get('title',''), precio_actual, precio_original, porcentaje, p.get('permalink',''), p.get('tienda',''), p.get('thumbnail',''))
                total = enviar_alertas([alerta], nombre, total)
            elif porcentaje >= UMBRAL_OFERTA:
                tipo = '🔥 OFERTA DETECTADA\n🏪 Tienda: ' + p.get('tienda', '')
                alerta = (tipo, p.get('title',''), precio_actual, precio_original, porcentaje, p.get('permalink',''), p.get('tienda',''), p.get('thumbnail',''))
                total = enviar_alertas([alerta], nombre, total)
        time.sleep(1)
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

@bot_telebot.message_handler(commands=['ofertas'])
def cmd_ofertas(message):
    historial = cargar_historial()
    if not historial:
        bot_telebot.reply_to(message, "📭 Aún no hay productos escaneados. Espera el primer ciclo.")
        return
    # Filtrar productos con descuento
    con_descuento = []
    for item_id, datos in historial.items():
        precio = datos.get('precio', 0)
        precio_original = datos.get('precio_original', 0)
        if precio_original > precio > 0:
            pct = ((precio_original - precio) / precio_original) * 100
            if pct >= UMBRAL_OFERTA:
                con_descuento.append((pct, datos.get('titulo', ''), precio, precio_original, datos.get('link', '')))
    if not con_descuento:
        bot_telebot.reply_to(message, f"📭 Sin ofertas sobre {UMBRAL_OFERTA}% en el historial actual.")
        return
    con_descuento.sort(reverse=True)
    top = con_descuento[:10]
    lineas = ["<b>Top ofertas detectadas:</b>"]
    for i, (pct, titulo, precio, link) in enumerate(top, 1):
        lineas.append(str(i) + ". <b>" + titulo[:50] + "</b>")
        lineas.append("$" + f"{precio:,.0f}" + " CLP (" + f"{pct:.1f}" + "% OFF)")
        if link:
            lineas.append(link)
        lineas.append("")
    bot_telebot.reply_to(message, "\n".join(lineas), parse_mode='HTML')
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
    while True:
        try:
            bot_telebot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error (reintentando en 15s): {e}")
            time.sleep(15)

def main():
    print("🤖 Monitor de Precios Chile iniciado")
    print(f"🏪 Tiendas: {', '.join([t[0] for t in TIENDAS])}")

    # Iniciar listener de comandos en hilo separado
    hilo_comandos = threading.Thread(target=iniciar_bot_comandos, daemon=True)
    hilo_comandos.start()

    enviar_telegram(
        "🤖 <b>Captador de Ofertas Chile activo</b>\n\n"
        "🏪 Tiendas: MercadoLibre, Ripley, Falabella\n"
        "📦 +2.000 artículos monitoreados\n"
        "🔄 Revisión cada 30 minutos\n\n"
        "Comandos: /estado /buscar /umbral /error /pausa /activar"
    )

    ejecutar_monitoreo()
    schedule.every(30).minutes.do(ejecutar_monitoreo)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
