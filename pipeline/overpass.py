"""
pipeline/overpass.py
Consultas a la API Overpass de OpenStreetMap para obtener POIs turísticos.
Fuente: https://overpass-api.de  (GRATIS, sin API key)

Esta es la fuente INNOVADORA del proyecto: nos permite obtener datos
geoespaciales en tiempo real de monumentos, museos y patrimonio de España.
"""

import requests
import time

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]
HEADERS = {"User-Agent": "TurismoSemantico/1.0 (universidad; proyecto academico)"}


def _overpass_query(
    query: str,
    timeout: int = 30,
    retries: int = 1,
    max_urls: int | None = None,
    max_total_seconds: float | None = None,
) -> list[dict]:
    """Ejecuta una consulta Overpass QL y devuelve los elementos."""
    last_err = None
    urls = OVERPASS_URLS[:max_urls] if max_urls else OVERPASS_URLS
    start = time.monotonic()
    for url in urls:
        if max_total_seconds and (time.monotonic() - start) > max_total_seconds:
            break
        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    url,
                    data={"data": query},
                    headers=HEADERS,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except Exception as e:
                last_err = f"{url}: {e}"
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))
        print(f"[Overpass] Error: {last_err}")
    return []


def _split_bbox(limit_bbox: tuple, rows: int = 2, cols: int = 2) -> list[tuple]:
    s, w, n, e = limit_bbox
    lat_step = (n - s) / rows
    lon_step = (e - w) / cols
    tiles = []
    for i in range(rows):
        for j in range(cols):
            tiles.append((
                s + i * lat_step,
                w + j * lon_step,
                s + (i + 1) * lat_step,
                w + (j + 1) * lon_step,
            ))
    return tiles


def _dedupe_elements(elements: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for el in elements:
        key = f"{el.get('type', '')}_{el.get('id')}"
        if key in seen:
            continue
        seen.add(key)
        output.append(el)
    return output


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
            "id": f"osm_{el.get('type', 'item')}_{el['id']}",
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


def get_patrimonio_nacional(
    limit_bbox: tuple = (36.0, -9.5, 43.8, 4.5),
    max_results: int = 220,
    max_total_seconds: float = 90.0,
) -> list[dict]:
    """
    Obtiene castillos y patrimonio histórico nacional en la bbox de España.
    bbox = (lat_min, lon_min, lat_max, lon_max)
    """
    tiles = _split_bbox(limit_bbox, rows=3, cols=3)
    elementos = []
    start = time.monotonic()

    for ts, tw, tn, te in tiles:
        remaining = max_total_seconds - (time.monotonic() - start)
        if remaining <= 0:
            break
        query = f"""
        [out:json][timeout:20];
        (
            node["historic"~"castle|monument|ruins|archaeological_site|fort|city_gate"]["name"]({ts},{tw},{tn},{te});
            way["historic"~"castle|monument|ruins|archaeological_site|fort|city_gate"]["name"]({ts},{tw},{tn},{te});
            node["heritage"]["name"]({ts},{tw},{tn},{te});
            way["heritage"]["name"]({ts},{tw},{tn},{te});
            node["tourism"~"museum|attraction|artwork|gallery"]["name"]({ts},{tw},{tn},{te});
            way["tourism"~"museum|attraction|artwork|gallery"]["name"]({ts},{tw},{tn},{te});
            node["amenity"="place_of_worship"]["name"]["historic"]({ts},{tw},{tn},{te});
            way["amenity"="place_of_worship"]["name"]["historic"]({ts},{tw},{tn},{te});
        );
        out center tags;
        """
        elementos.extend(_overpass_query(
            query,
            timeout=min(20, max(8, int(remaining))),
            retries=0,
            max_urls=1,
            max_total_seconds=min(24, remaining),
        ))
        if len(_dedupe_elements(elementos)) >= max_results:
            break

    elementos = _dedupe_elements(elementos)
    results = []
    for el in elementos[:max_results]:
        tags = el.get("tags", {})
        nombre = tags.get("name:es") or tags.get("name")
        if not nombre:
            continue
        lat_el = el.get("lat") or el.get("center", {}).get("lat")
        lon_el = el.get("lon") or el.get("center", {}).get("lon")
        if not lat_el or not lon_el:
            continue
        results.append({
            "id": f"osm_{el.get('type', 'item')}_{el['id']}",
            "nombre": nombre,
            "lat": float(lat_el),
            "lon": float(lon_el),
            "tipo_osm": tags.get("tourism") or tags.get("historic") or tags.get("amenity") or "patrimonio",
            "descripcion": tags.get("description:es") or tags.get("description", ""),
            "web": tags.get("website", ""),
            "wikipedia": tags.get("wikipedia", ""),
            "imagen": tags.get("image", ""),
            "fuente": "OpenStreetMap",
        })
    return results
