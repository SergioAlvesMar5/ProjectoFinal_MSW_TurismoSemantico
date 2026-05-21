"""
pipeline/overpass.py
Consultas a la API Overpass de OpenStreetMap para obtener POIs turísticos.
Fuente: https://overpass-api.de  (GRATIS, sin API key)

Esta es la fuente INNOVADORA del proyecto: nos permite obtener datos
geoespaciales en tiempo real de monumentos, museos y patrimonio de España.
"""

import requests
import time

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "TurismoSemantico/1.0 (universidad; proyecto academico)"}


def _overpass_query(query: str, timeout: int = 30) -> list[dict]:
    """Ejecuta una consulta Overpass QL y devuelve los elementos."""
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("elements", [])
    except Exception as e:
        print(f"[Overpass] Error: {e}")
        return []


def get_monumentos_ciudad(ciudad: str, radio_km: float = 10.0) -> list[dict]:
    """
    Busca monumentos y patrimonio histórico en una ciudad española.
    Usa geocodificación Nominatim para obtener las coordenadas de la ciudad.
    """
    # Paso 1: geocodificar la ciudad
    try:
        geo = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{ciudad}, Spain", "format": "json", "limit": 1},
            headers=HEADERS,
            timeout=10,
        ).json()
        if not geo:
            return []
        lat, lon = float(geo[0]["lat"]), float(geo[0]["lon"])
    except Exception as e:
        print(f"[Nominatim] Error geocodificando '{ciudad}': {e}")
        return []

    radio_m = int(radio_km * 1000)

    # Paso 2: buscar POIs turísticos con Overpass
    query = f"""
    [out:json][timeout:25];
    (
      node["tourism"="museum"](around:{radio_m},{lat},{lon});
      node["tourism"="attraction"](around:{radio_m},{lat},{lon});
      node["historic"="monument"](around:{radio_m},{lat},{lon});
      node["historic"="castle"](around:{radio_m},{lat},{lon});
      node["amenity"="place_of_worship"]["name"](around:{radio_m},{lat},{lon});
      way["tourism"="museum"](around:{radio_m},{lat},{lon});
      way["historic"="monument"](around:{radio_m},{lat},{lon});
      way["historic"="castle"](around:{radio_m},{lat},{lon});
    );
    out center tags;
    """
    elementos = _overpass_query(query)
    results = []
    for el in elementos:
        tags = el.get("tags", {})
        nombre = (
            tags.get("name:es")
            or tags.get("name")
            or tags.get("official_name")
        )
        if not nombre:
            continue
        lat_el = el.get("lat") or el.get("center", {}).get("lat")
        lon_el = el.get("lon") or el.get("center", {}).get("lon")
        if not lat_el or not lon_el:
            continue
        results.append({
            "id": f"osm_{el['id']}",
            "nombre": nombre,
            "lat": float(lat_el),
            "lon": float(lon_el),
            "tipo_osm": tags.get("tourism") or tags.get("historic") or tags.get("amenity", ""),
            "descripcion": tags.get("description:es") or tags.get("description", ""),
            "web": tags.get("website", ""),
            "wikipedia": tags.get("wikipedia", ""),
            "imagen": tags.get("image", ""),
            "fuente": "OpenStreetMap",
        })
    return results


def get_patrimonio_nacional(limit_bbox: tuple = (36.0, -9.5, 43.8, 4.5)) -> list[dict]:
    """
    Obtiene castillos y patrimonio histórico nacional en la bbox de España.
    bbox = (lat_min, lon_min, lat_max, lon_max)
    """
    s, w, n, e = limit_bbox
    query = f"""
    [out:json][timeout:40];
    (
      node["historic"="castle"]({s},{w},{n},{e});
      node["historic"="ruins"]({s},{w},{n},{e});
      node["heritage"]["name"]({s},{w},{n},{e});
      way["historic"="castle"]({s},{w},{n},{e});
      way["heritage"]["name"]({s},{w},{n},{e});
    );
    out center tags;
    """
    elementos = _overpass_query(query, timeout=45)
    results = []
    for el in elementos[:60]:  # max 60
        tags = el.get("tags", {})
        nombre = tags.get("name:es") or tags.get("name")
        if not nombre:
            continue
        lat_el = el.get("lat") or el.get("center", {}).get("lat")
        lon_el = el.get("lon") or el.get("center", {}).get("lon")
        if not lat_el or not lon_el:
            continue
        results.append({
            "id": f"osm_{el['id']}",
            "nombre": nombre,
            "lat": float(lat_el),
            "lon": float(lon_el),
            "tipo_osm": tags.get("historic", "patrimonio"),
            "descripcion": tags.get("description:es") or tags.get("description", ""),
            "fuente": "OpenStreetMap",
        })
    return results
