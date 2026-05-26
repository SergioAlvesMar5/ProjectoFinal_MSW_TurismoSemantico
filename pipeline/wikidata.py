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
UNESCO_YEAR_FALLBACKS = {
    # Wikidata marca estos recursos como UNESCO, pero no incluye fecha en la
    # declaración directa. Se toma el año del bien UNESCO agregado.
    "Q33200": "1984",
    "Q98824936": "1993",
    "Q131764534": "1998",
}


def _run_query(sparql: str, timeout: int = 20, max_retries: int = 1) -> tuple[list[dict], str | None]:
    """Ejecuta una consulta SPARQL y devuelve (bindings, error)."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(
                SPARQL_ENDPOINT,
                params={"query": sparql, "format": "json"},
                headers=HEADERS,
                timeout=timeout,
            )
            if resp.status_code != 200:
                preview = (resp.text or "")[:300].replace("\n", " ")
                last_err = f"HTTP {resp.status_code}: {preview}"
            else:
                return resp.json()["results"]["bindings"], None
        except Exception as e:
            last_err = str(e)

        if attempt < max_retries:
            time.sleep(1.5 * (attempt + 1))

    print(f"[Wikidata] Error: {last_err}")
    return [], last_err


def _year_from_wikidata_value(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip()
    if value.startswith("-"):
        return ""
    year = value[:4]
    return year if year.isdigit() else ""


def get_destinos_patrimonio_unesco(limit: int = 30) -> list[dict]:
    """
    Devuelve ciudades/sitios de España declarados Patrimonio UNESCO.
    Incluye: nombre, coordenadas, descripción corta, imagen, año de declaración.
    """
    query = f"""
    SELECT DISTINCT ?lugar ?lugarLabel ?coord ?imagen ?descripcion
                    ?anioDirecto ?anioParte ?inicio WHERE {{
      ?lugar wdt:P17 wd:Q29 ;
             wdt:P1435 wd:Q9259 ;
             wdt:P625 ?coord .
      OPTIONAL {{ ?lugar wdt:P18 ?imagen . }}
      OPTIONAL {{ ?lugar schema:description ?descripcion .
                  FILTER(LANG(?descripcion) = "es") }}
      OPTIONAL {{
        ?lugar p:P1435 ?declaracion .
        ?declaracion ps:P1435 wd:Q9259 .
        OPTIONAL {{ ?declaracion pq:P580 ?anioDirecto . }}
        OPTIONAL {{ ?declaracion pq:P585 ?anioDirecto . }}
      }}
      OPTIONAL {{
        ?lugar (wdt:P361|wdt:P131)* ?bienAgregado .
        FILTER(?bienAgregado != ?lugar)
        ?bienAgregado p:P1435 ?declaracionAgregada .
        ?declaracionAgregada ps:P1435 wd:Q9259 .
        OPTIONAL {{ ?declaracionAgregada pq:P580 ?anioParte . }}
        OPTIONAL {{ ?declaracionAgregada pq:P585 ?anioParte . }}
      }}
      OPTIONAL {{ ?lugar wdt:P571 ?inicio . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT {limit}
    """
    rows, err = _run_query(query, timeout=25)
    if err:
        return []
    results_by_id = {}
    for r in rows:
        try:
            coord_str = r["coord"]["value"]  # "Point(lon lat)"
            lon, lat = coord_str.replace("Point(", "").replace(")", "").split()
            qid = r["lugar"]["value"].split("/")[-1]
            year = (
                _year_from_wikidata_value(r.get("anioDirecto", {}).get("value"))
                or _year_from_wikidata_value(r.get("anioParte", {}).get("value"))
                or UNESCO_YEAR_FALLBACKS.get(qid, "")
                or _year_from_wikidata_value(r.get("inicio", {}).get("value"))
            )
            current = results_by_id.get(qid)
            if current and current.get("anio_patrimonio"):
                continue
            results_by_id[qid] = {
                "id": qid,
                "nombre": r["lugarLabel"]["value"],
                "lat": float(lat),
                "lon": float(lon),
                "imagen": r.get("imagen", {}).get("value", ""),
                "descripcion": r.get("descripcion", {}).get("value", ""),
                "anio_patrimonio": year,
                "tipo": "patrimonio_unesco",
                "wikidata_id": qid,
            }
        except Exception:
            continue
    return list(results_by_id.values())


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
    rows, err = _run_query(query, timeout=25)
    if err:
        return []
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
    rows, err = _run_query(query, timeout=20)
    if err:
        return {}
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
    location_primary = """
      ?lugar wdt:P17 wd:Q29 .
      FILTER(?lugar != wd:Q29)
    """

    location_fallback = """
      {
        ?lugar wdt:P17 wd:Q29 .
      } UNION {
        ?lugar wdt:P131* wd:Q29 .
      }
      FILTER(?lugar != wd:Q29)
    """

    base_types = [
        "wd:Q2221906",  # tourist attraction (original)
        "wd:Q570116",   # tourist attraction (alt)
        "wd:Q839954",   # cultural heritage
        "wd:Q4989906",  # monument
        "wd:Q17350442", # historic site
        "wd:Q515",      # city
    ]

    values = " ".join(base_types)
    query_primary = f"""
    SELECT DISTINCT ?lugar ?lugarLabel ?desc ?coord ?tipo ?tipoLabel WHERE {{
      {location_primary}
      ?lugar wdt:P625 ?coord ;
             wdt:P31 ?tipo .
      VALUES ?tipo {{ {values} }}
      OPTIONAL {{
        ?lugar schema:description ?desc .
        FILTER(LANG(?desc) = "es")
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
    }}
    LIMIT {limit}
    """
    rows, err = _run_query(query_primary, timeout=25)
    if err:
        return []

    if not rows:
        query_fallback = f"""
        SELECT DISTINCT ?lugar ?lugarLabel ?desc ?coord ?tipo ?tipoLabel WHERE {{
          {location_primary}
          ?lugar wdt:P625 ?coord ;
                 wdt:P31 ?tipo .
          ?tipo wdt:P279* ?baseType .
          VALUES ?baseType {{ {values} }}
          OPTIONAL {{
            ?lugar schema:description ?desc .
            FILTER(LANG(?desc) = "es")
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
        }}
        LIMIT {limit}
        """
        rows, err = _run_query(query_fallback, timeout=25)
        if err:
            return []

    if not rows:
        query_relaxed = f"""
        SELECT DISTINCT ?lugar ?lugarLabel ?desc ?coord WHERE {{
          {location_fallback}
          ?lugar wdt:P625 ?coord .
          OPTIONAL {{
            ?lugar schema:description ?desc .
            FILTER(LANG(?desc) = "es")
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
        }}
        LIMIT {limit}
        """
        rows, err = _run_query(query_relaxed, timeout=30)
        if err:
            return []

    if not rows:
        print("[Wikidata] Sin resultados para destinos generales.")
        return []

    results = []
    for r in rows:
        try:
            coord_str = r["coord"]["value"]
            lon, lat = coord_str.replace("Point(", "").replace(")", "").split()
            nombre = r["lugarLabel"]["value"]
            desc   = r.get("desc", {}).get("value", f"Destino turístico en España: {nombre}")
            tipo_label = r.get("tipoLabel", {}).get("value", "destino")
            results.append({
                "id": r["lugar"]["value"].split("/")[-1],
                "nombre": nombre,
                "lat": float(lat),
                "lon": float(lon),
                "descripcion": desc,
                "tipo": tipo_label,
                "wikidata_id": r["lugar"]["value"].split("/")[-1],
                "texto_embedding": f"{nombre}. {desc}",
            })
        except Exception:
            continue
    return results
