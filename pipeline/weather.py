"""
pipeline/weather.py
Datos meteorológicos en tiempo real con Open-Meteo API.
Fuente: https://api.open-meteo.com  (GRATIS, sin API key — FUENTE INNOVADORA)
"""

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Códigos WMO de tiempo → descripción + emoji
WMO_CODES = {
    0: ("Despejado", "☀️"), 1: ("Mayormente despejado", "🌤️"),
    2: ("Parcialmente nublado", "⛅"), 3: ("Nublado", "☁️"),
    45: ("Niebla", "🌫️"), 48: ("Niebla con escarcha", "🌫️"),
    51: ("Llovizna ligera", "🌦️"), 53: ("Llovizna moderada", "🌦️"),
    55: ("Llovizna densa", "🌧️"), 61: ("Lluvia ligera", "🌧️"),
    63: ("Lluvia moderada", "🌧️"), 65: ("Lluvia fuerte", "🌧️"),
    71: ("Nevada ligera", "🌨️"), 73: ("Nevada moderada", "❄️"),
    75: ("Nevada intensa", "❄️"), 80: ("Chubascos ligeros", "🌦️"),
    81: ("Chubascos moderados", "🌧️"), 82: ("Chubascos fuertes", "⛈️"),
    95: ("Tormenta", "⛈️"), 96: ("Tormenta con granizo", "⛈️"),
    99: ("Tormenta intensa con granizo", "⛈️"),
}


def get_clima(lat: float, lon: float) -> dict:
    """
    Devuelve el tiempo actual y la previsión de 3 días para unas coordenadas.
    """
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                "timezone": "Europe/Madrid",
                "forecast_days": 4,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        cw   = data["current_weather"]
        code = int(cw.get("weathercode", 0))
        desc, emoji = WMO_CODES.get(code, ("Desconocido", "❓"))

        # Previsión diaria
        daily = data.get("daily", {})
        forecast = []
        for i in range(min(4, len(daily.get("time", [])))):
            dc = int(daily["weathercode"][i]) if daily.get("weathercode") else 0
            d_desc, d_emoji = WMO_CODES.get(dc, ("", ""))
            forecast.append({
                "fecha":     daily["time"][i],
                "max":       daily["temperature_2m_max"][i],
                "min":       daily["temperature_2m_min"][i],
                "precip":    daily["precipitation_sum"][i],
                "descripcion": d_desc,
                "emoji":     d_emoji,
            })

        return {
            "temperatura":   round(cw["temperature"], 1),
            "viento_kmh":    round(cw.get("windspeed", 0), 1),
            "descripcion":   desc,
            "emoji":         emoji,
            "es_dia":        cw.get("is_day", 1),
            "forecast":      forecast,
            "fuente":        "Open-Meteo (api.open-meteo.com)",
        }
    except Exception as e:
        print(f"[Open-Meteo] Error: {e}")
        return {
            "temperatura": None,
            "descripcion": "No disponible",
            "emoji": "❓",
            "forecast": [],
        }
