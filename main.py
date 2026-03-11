import subprocess
import sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "schedule", "beautifulsoup4", "lxml"])

import requests
import json
import time
import schedule
import os
from datetime import datetime
from bs4 import BeautifulSoup

# ─── CONFIGURACIÓN ───────────────────────────────────────────
TELEGRAM_TOKEN = "8754880187:AAHojj4MMgZRKT0XaOnTVsb8QBiqDP7Kzbo"
CHAT_ID = "8428923831"
PRECIO_HISTORIAL_FILE = "historial_precios.json"
UMBRAL_OFERTA = 20
UMBRAL_ERROR = 40

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

        if not precio_actual:
            continue

        descuento_vendedor = calcular_variacion(precio_actual, precio_original)
        precio_anterior = historial.get(item_id, {}).get('precio', 0)
        variacion_historica = calcular_variacion(precio_actual, precio_anterior) if precio_anterior > 0 else 0

        historial[item_id] = {
            'precio': precio_actual,
            'titulo': titulo,
            'ultima_vez': datetime.now().isoformat()
        }

        porcentaje = max(descuento_vendedor, variacion_historica)

        if porcentaje >= UMBRAL_ERROR:
            tipo = '🚨 POSIBLE ERROR DE PRECIO\n🏪 Tienda: ' + tienda
            alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url))
        elif porcentaje >= UMBRAL_OFERTA:
            tipo = '🔥 OFERTA DETECTADA\n🏪 Tienda: ' + tienda
            alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, tienda, foto_url))

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
    url = f'https://simple.ripley.cl/api/2.0/page/search/?query={query}&page=1&perPage=50'
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        data = response.json()
        resultados = []
        for p in data.get('results', []):
            precio_actual = p.get('prices', {}).get('normalPrice', 0)
            precio_original = p.get('prices', {}).get('originalPrice') or precio_actual
            if not precio_actual:
                continue
            resultados.append({
                'id': 'rip_' + str(p.get('partNumber', '')),
                'title': p.get('displayName', ''),
                'price': float(precio_actual),
                'original_price': float(precio_original),
                'permalink': 'https://simple.ripley.cl' + p.get('url', ''),
                'thumbnail': p.get('image', ''),
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
def buscar_hites(query):
    url = f'https://www.hites.com/search?q={query}&sort=price-asc&hitsPerPage=50'
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
            link = 'https://www.hites.com' + link_el['href'] if link_el and link_el.get('href') else ''
            imagen = img_el.get('src', '') if img_el else ''
            resultados.append({
                'id': 'hit_' + titulo[:30].replace(' ', '_'),
                'title': titulo,
                'price': precio_actual,
                'original_price': precio_actual,
                'permalink': link,
                'thumbnail': imagen,
                'tienda': 'Hites.cl'
            })
        return resultados
    except Exception as e:
        print(f"Error Hites ({query}): {e}")
        return []


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
    ('MercadoLibre', buscar_mercadolibre, BUSQUEDAS),
    ('Ripley',       buscar_ripley,       BUSQUEDAS[:20]),
    ('Falabella',    buscar_falabella,    BUSQUEDAS[:20]),
    ('Paris',        buscar_paris,        BUSQUEDAS[:20]),
    ('Sodimac',      buscar_sodimac,      ['taladro', 'set herramientas', 'refrigerador', 'lavadora', 'aire acondicionado', 'sofa', 'colchon', 'lampara', 'escritorio', 'aspiradora']),
    ('Hites',        buscar_hites,        BUSQUEDAS[:20]),
    ('LaPolar',      buscar_lapolar,      BUSQUEDAS[:20]),
    ('AbcDin',       buscar_abcdin,       BUSQUEDAS[:20]),
]


def ejecutar_monitoreo():
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
    print(f"\n  ✅ Ciclo completado. Alertas enviadas: {total_alertas}")


def main():
    print("🤖 Monitor de Precios Chile iniciado")
    print(f"🏪 Tiendas: {', '.join([t[0] for t in TIENDAS])}")

    enviar_telegram(
        "🤖 <b>Monitor de Precios Chile activo</b>\n\n"
        "🏪 Tiendas: MercadoLibre, Ripley, Falabella, Paris, Sodimac, Hites, LaPolar, AbcDin, PCFactory, Linio\n"
        "📦 +3.500 artículos monitoreados\n"
        "🔄 Revisión cada 30 minutos"
    )

    ejecutar_monitoreo()
    schedule.every(30).minutes.do(ejecutar_monitoreo)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
