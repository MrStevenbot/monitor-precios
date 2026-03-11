import subprocess
import sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "schedule"])

import requests
import json
import time
import schedule
import os
from datetime import datetime

# ─── CONFIGURACIÓN ───────────────────────────────────────────
TELEGRAM_TOKEN = "8754880187:AAHojj4MMgZRKT0XaOnTVsb8QBiqDP7Kzbo"
CHAT_ID = "8428923831"
PRECIO_HISTORIAL_FILE = "historial_precios.json"

# Porcentaje de bajada para considerar alerta (20% = oferta, 40%+ = posible error)
UMBRAL_OFERTA = 20
UMBRAL_ERROR = 40

# Palabras clave a monitorear en MercadoLibre Chile
BUSQUEDAS = [
    # Tecnología
    "notebook",
    "smartphone",
    "televisor",
    "tablet",
    "iphone",
    "samsung galaxy",
    "consola videojuegos",
    "camara fotografica",
    "auriculares",
    "smartwatch",
    "parlante bluetooth",
    "drone",
    "Mando Play 5",
    # Electrohogar
    "refrigerador",
    "lavadora",
    "microondas",
    "aire acondicionado",
    "aspiradora",
    "cafetera",
    "Freidora de Aire",
    # Deportes
    "bicicleta",
    "bicicleta electrica",
    "zapatillas running",
    "zapatillas nike",
    "zapatillas adidas",
    "trotadora",
    "pesas",
    # Ropa y moda
    "chaqueta",
    "poleron",
    "jeans",
    "vestido",
    "ropa deportiva",
    # Perfumes y belleza
    "perfume hombre",
    "Armaf",
    "Rasasi",
    "perfume mujer",
    "crema facial",
    "maquillaje",
    # Hogar y muebles
    "sofa",
    "escritorio",
    "silla gamer",
    "colchon",
    "lampara",
    # Herramientas
    "taladro",
    "set herramientas",
    # Juguetes
    "lego",
    "juguete niños",
    # Mascotas
    "alimento perro",
    "juguetes perros",
    "alimento gato",
    # Autos y motos
    "accesorios auto",

]
# ─────────────────────────────────────────────────────────────


def enviar_telegram(mensaje, foto_url=None):
    try:
        if foto_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            payload = {
                "chat_id": CHAT_ID,
                "photo": foto_url,
                "caption": mensaje,
                "parse_mode": "HTML"
            }
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": CHAT_ID,
                "text": mensaje,
                "parse_mode": "HTML"
            }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        return False


def cargar_historial():
    if os.path.exists(PRECIO_HISTORIAL_FILE):
        with open(PRECIO_HISTORIAL_FILE, "r") as f:
            return json.load(f)
    return {}


def guardar_historial(historial):
    with open(PRECIO_HISTORIAL_FILE, "w") as f:
        json.dump(historial, f, indent=2, ensure_ascii=False)


def buscar_mercadolibre(query, limite=50):
    url = "https://api.mercadolibre.com/sites/MLC/search"
    params = {
        "q": query,
        "limit": limite,
        "sort": "price_asc"
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        return data.get("results", [])
    except Exception as e:
        print(f"Error consultando MercadoLibre: {e}")
        return []


def calcular_variacion(precio_actual, precio_anterior):
    if precio_anterior == 0:
        return 0
    return ((precio_anterior - precio_actual) / precio_anterior) * 100


def analizar_productos(productos, historial, query):
    alertas = []

    for producto in productos:
        item_id = producto.get("id")
        titulo = producto.get("title", "Sin título")
        precio_actual = producto.get("price", 0)
        precio_original = producto.get("original_price") or precio_actual
        link = producto.get("permalink", "")
        foto_url = producto.get("thumbnail", "").replace("I.jpg", "O.jpg")
        vendedor = producto.get("seller", {}).get("nickname", "Desconocido")

        # Calcular descuento del vendedor (precio original vs actual)
        descuento_vendedor = calcular_variacion(precio_actual, precio_original)

        # Calcular variación histórica (nuestro registro)
        precio_anterior = historial.get(item_id, {}).get("precio", 0)
        variacion_historica = calcular_variacion(precio_actual, precio_anterior) if precio_anterior > 0 else 0

        # Actualizar historial
        historial[item_id] = {
            "precio": precio_actual,
            "titulo": titulo,
            "ultima_vez": datetime.now().isoformat()
        }

        # Detectar alertas
        if descuento_vendedor >= UMBRAL_ERROR or variacion_historica >= UMBRAL_ERROR:
            tipo = "🚨 POSIBLE ERROR DE PRECIO"
            porcentaje = max(descuento_vendedor, variacion_historica)
            alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, vendedor, foto_url))

        elif descuento_vendedor >= UMBRAL_OFERTA or variacion_historica >= UMBRAL_OFERTA:
            tipo = "🔥 OFERTA DETECTADA"
            porcentaje = max(descuento_vendedor, variacion_historica)
            alertas.append((tipo, titulo, precio_actual, precio_original, porcentaje, link, vendedor, foto_url))

    return alertas, historial


def formatear_alerta(tipo, titulo, precio_actual, precio_original, porcentaje, link, vendedor, foto_url=None):
    precio_actual_fmt = f"${precio_actual:,.0f} CLP"
    precio_original_fmt = f"${precio_original:,.0f} CLP"

    mensaje = (
        f"{tipo}\n\n"
        f"📦 <b>{titulo}</b>\n"
        f"💰 Precio actual: <b>{precio_actual_fmt}</b>\n"
        f"📊 Precio anterior: {precio_original_fmt}\n"
        f"📉 Bajó: <b>{porcentaje:.1f}%</b>\n"
        f"🏪 Vendedor: {vendedor}\n"
        f"🔗 {link}"
    )
    return mensaje


def ejecutar_monitoreo():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Iniciando monitoreo...")
    historial = cargar_historial()
    total_alertas = 0

    for query in BUSQUEDAS:
        print(f"  Buscando: {query}")
        productos = buscar_mercadolibre(query)

        if not productos:
            print(f"  Sin resultados para: {query}")
            continue

        alertas, historial = analizar_productos(productos, historial, query)

        for alerta in alertas:
            mensaje = formatear_alerta(*alerta)
            enviado = enviar_telegram(mensaje, foto_url=alerta[7] if len(alerta) > 7 else None)
            if enviado:
                print(f"  ✅ Alerta enviada: {alerta[1][:50]}...")
                total_alertas += 1
            time.sleep(1)  # Evitar spam a Telegram

        time.sleep(2)  # Respetar límites de la API

    guardar_historial(historial)
    print(f"  Monitoreo completado. Alertas enviadas: {total_alertas}")


def main():
    print("🤖 Monitor de Precios Chile iniciado")
    print(f"📊 Monitoreando: {', '.join(BUSQUEDAS)}")
    print(f"🔔 Alertas → Telegram Chat ID: {CHAT_ID}")
    print(f"⚙️  Umbral oferta: {UMBRAL_OFERTA}% | Umbral error: {UMBRAL_ERROR}%\n")

    # Enviar mensaje de inicio
    enviar_telegram(
        "🤖 <b>Monitor de Precios Chile activo</b>\n\n"
        f"Monitoreando: {', '.join(BUSQUEDAS)}\n"
        f"Revisión cada 30 minutos."
    )

    # Ejecutar inmediatamente al iniciar
    ejecutar_monitoreo()

    # Programar cada 30 minutos
    schedule.every(30).minutes.do(ejecutar_monitoreo)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
