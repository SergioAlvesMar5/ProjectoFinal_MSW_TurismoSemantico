"""
pipeline/wikidata.py
Consultas SPARQL a Wikidata para obtener destinos turísticos de España.
Fuente: https://query.wikidata.org/sparql  (GRATIS, sin API key)
"""

import requests
import json
import time

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "TurismoSemantico/1.0 (universidad; proyecto academico)",
    "Accept": "application/sparql-results+json",
}


def _run_query(sparql: str, timeout: int = 20) -> list[dict]:
    """Ejecuta una consulta SPARQL y devuelve la lista de bindings."""
    try:
        resp = requests.get(
            SPARQL_ENDPOINT,
            params={"query": sparql, "format": "json"},
            headers=HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["results"]["bindings"]
    except Exception as e:
        print(f"[Wikidata] Error: {e}")
        return []


def get_destinos_patrimonio_unesco(limit: int = 30) -> list[dict]:
    """
    Devuelve ciudades/sitios de España declarados Patrimonio UNESCO.
    Incluye: nombre, coordenadas, descripción corta, imagen, año de declaración.
    """
    query = f"""
    SELECT DISTINCT ?lugar ?lugarLabel ?coord ?imagen ?descripcion ?anio WHERE {{
      ?lugar wdt:P17 wd:Q29 ;
             wdt:P1435 wd:Q9259 ;
             wdt:P625 ?coord .
      OPTIONAL {{ ?lugar wdt:P18 ?imagen . }}
      OPTIONAL {{ ?lugar schema:description ?descripcion .
                  FILTER(LANG(?descripcion) = "es") }}
      OPTIONAL {{ ?lugar wdt:P571 ?anio . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT {limit}
    """
    rows = _run_query(query)
    results = []
    for r in rows:
        try:
            coord_str = r["coord"]["value"]  # "Point(lon lat)"
            lon, lat = coord_str.replace("Point(", "").replace(")", "").split()
            results.append({
                "id": r["lugar"]["value"].split("/")[-1],
                "nombre": r["lugarLabel"]["value"],
                "lat": float(lat),
                "lon": float(lon),
                "imagen": r.get("imagen", {}).get("value", ""),
                "descripcion": r.get("descripcion", {}).get("value", ""),
                "anio_patrimonio": r.get("anio", {}).get("value", "")[:4] if r.get("anio") else "",
                "tipo": "patrimonio_unesco",
                "wikidata_id": r["lugar"]["value"].split("/")[-1],
            })
        except Exception:
            continue
    return results


def get_museos_espana(limit: int = 40) -> list[dict]:
    """
    Devuelve museos de España con coordenadas y datos básicos.
    """
    query = f"""
    SELECT DISTINCT ?museo ?museoLabel ?coord ?imagen ?ciudad ?ciudadLabel WHERE {{
      ?museo wdt:P31/wdt:P279* wd:Q33506 ;
             wdt:P17 wd:Q29 ;
             wdt:P625 ?coord .
      OPTIONAL {{ ?museo wdt:P18 ?imagen . }}
      OPTIONAL {{ ?museo wdt:P131 ?ciudad . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT {limit}
    """
    rows = _run_query(query)
    results = []
    for r in rows:
        try:
            coord_str = r["coord"]["value"]
            lon, lat = coord_str.replace("Point(", "").replace(")", "").split()
            results.append({
                "id": r["museo"]["value"].split("/")[-1],
                "nombre": r["museoLabel"]["value"],
                "lat": float(lat),
                "lon": float(lon),
                "imagen": r.get("imagen", {}).get("value", ""),
                "ciudad": r.get("ciudadLabel", {}).get("value", ""),
                "tipo": "museo",
                "wikidata_id": r["museo"]["value"].split("/")[-1],
            })
        except Exception:
            continue
    return results


def get_detalles_lugar(wikidata_id: str) -> dict:
    """
    Devuelve información detallada de un lugar: tipo, relaciones, etc.
    """
    query = f"""
    SELECT ?prop ?propLabel ?value ?valueLabel WHERE {{
      wd:{wikidata_id} ?p ?value .
      ?prop wikibase:directClaim ?p .
      VALUES ?p {{ wdt:P571 wdt:P18 wdt:P856 wdt:P131 wdt:P17
                   wdt:P276 wdt:P1566 wdt:P2044 wdt:P1087 }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT 20
    """
    rows = _run_query(query)
    detalles = {}
    for r in rows:
        prop = r.get("propLabel", {}).get("value", r["prop"]["value"])
        val  = r.get("valueLabel", {}).get("value", r["value"]["value"])
        detalles[prop] = val
    return detalles


def get_destinos_para_embeddings(limit: int = 80) -> list[dict]:
    """
    Devuelve una lista amplia de destinos con descripción textual para generar embeddings.
    """
    query = f"""
    SELECT DISTINCT ?lugar ?lugarLabel ?desc ?coord ?tipo ?tipoLabel WHERE {{
      ?lugar wdt:P17 wd:Q29 ;
             wdt:P625 ?coord ;
             wdt:P31 ?tipo .
      ?tipo wdt:P279* wd:Q2221906 .
      OPTIONAL {{
        ?lugar schema:description ?desc .
        FILTER(LANG(?desc) = "es")
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT {limit}
    """
    rows = _run_query(query)
    results = []
    for r in rows:
        try:
            coord_str = r["coord"]["value"]
            lon, lat = coord_str.replace("Point(", "").replace(")", "").split()
            nombre = r["lugarLabel"]["value"]
            desc   = r.get("desc", {}).get("value", f"Destino turístico en España: {nombre}")
            results.append({
                "id": r["lugar"]["value"].split("/")[-1],
                "nombre": nombre,
                "lat": float(lat),
                "lon": float(lon),
                "descripcion": desc,
                "tipo": r.get("tipoLabel", {}).get("value", "lugar"),
                "wikidata_id": r["lugar"]["value"].split("/")[-1],
                "texto_embedding": f"{nombre}. {desc}",
            })
        except Exception:
            continue
    return results
