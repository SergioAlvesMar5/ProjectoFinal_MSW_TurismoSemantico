"""
app.py — TurismoSemántico
Backend Flask que orquesta todas las fuentes de datos y expone la API REST
consumida por el frontend HTML/JS.

Rutas principales:
  GET  /                      → Frontend principal
  POST /api/cargar            → Carga y procesa datos de todas las fuentes
  GET  /api/destinos          → Lista de destinos del grafo
  GET  /api/buscar?q=texto    → Búsqueda semántica
  GET  /api/clima?lat=&lon=   → Clima en tiempo real (Open-Meteo)
  GET  /api/overpass?ciudad=  → POIs de OpenStreetMap para una ciudad
  POST /api/chat              → Chatbot RAG
  GET  /api/grafo             → Tripletas RDF para visualización
  GET  /api/sparql?q=         → Ejecutar SPARQL local
  GET  /api/estado            → Estado del sistema
"""

import json
import os
import time
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify

from pipeline import (
    get_destinos_patrimonio_unesco, get_museos_espana, get_destinos_para_embeddings,
    get_monumentos_ciudad, get_patrimonio_nacional,
    get_clima,
    construir_ontologia, poblar_grafo, grafo_a_json, sparql_local, SHACL_SHAPES,
    indexar_destinos, buscar_semantico, rag_pipeline, extraer_entidades,
)

app = Flask(__name__, template_folder="templates", static_folder="static")

# ── Estado global del sistema ────────────────────────────────────────────────
estado = {
    "cargado": False,
    "num_destinos": 0,
    "num_tripletas": 0,
    "embeddings_ok": False,
    "cargando": False,
    "error": "",
    "osm_status": "idle",
    "osm_count": 0,
    "osm_error": "",
    "log": [],
}
grafo_global = None
destinos_global: list[dict] = []
data_lock = threading.Lock()
osm_thread = None
osm_thread_lock = threading.Lock()

DATA_FILE = Path("data/destinos.json")
DATA_FILE.parent.mkdir(exist_ok=True)
OSM_CACHE_MIN_ITEMS = 120


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _int_arg(
    name: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> tuple[int | None, str | None]:
    raw = request.args.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Parametro {name} debe ser un entero"
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value, None


def _float_arg(
    name: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> tuple[float | None, str | None]:
    raw = request.args.get(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"Parametro {name} debe ser numerico"
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value, None


def log(msg: str):
    print(f"[app] {msg}")
    estado["log"].append(msg)
    if len(estado["log"]) > 50:
        estado["log"] = estado["log"][-50:]


def _load_cache_json(path: Path) -> list[dict] | None:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="latin-1")
            data = json.loads(text)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            log("Cache convertida a UTF-8.")
            return data
        except Exception as e:
            log(f"Error leyendo cache: {e}")
            return None
    except Exception as e:
        log(f"Error leyendo cache: {e}")
        return None


def _merge_destinos(base: list[dict], extra: list[dict]) -> list[dict]:
    merged = {}
    nombres = set()
    for d in base:
        key = _destino_key(d)
        if key:
            merged[key] = d
            nombre = (d.get("nombre") or "").strip().casefold()
            if nombre:
                nombres.add(nombre)
    for d in extra:
        key = _destino_key(d)
        nombre = (d.get("nombre") or "").strip().casefold()
        if key and key not in merged and nombre not in nombres:
            merged[key] = d
            if nombre:
                nombres.add(nombre)
    return list(merged.values())


def _destino_key(d: dict) -> str:
    if d.get("wikidata_id"):
        return f"wd:{d['wikidata_id']}"
    if d.get("id"):
        return str(d["id"])
    return (d.get("nombre") or "").strip().casefold()


def _tipo_visible(d: dict) -> str:
    return (d.get("tipo") or d.get("tipo_osm") or "destino").strip() or "destino"


def _normalizar_tipo(tipo: str) -> str:
    return (tipo or "").strip().casefold()


def _es_destino_generico(d: dict) -> bool:
    tipo = _normalizar_tipo(_tipo_visible(d))
    if not tipo:
        return True
    tipos_especiales = {
        "patrimonio_unesco", "museo", "museum", "castle", "castillo",
        "ruins", "ruinas", "attraction", "monument", "archaeological_site",
        "heritage", "place_of_worship", "artwork", "gallery",
    }
    if tipo in tipos_especiales:
        return False
    return (
        "destino" in tipo
        or "municipio" in tipo
        or "ciudad" in tipo
        or "localidad" in tipo
        or "pueblo" in tipo
        or d.get("fuente") != "OpenStreetMap"
    )


def _start_osm_background() -> bool:
    global osm_thread
    with osm_thread_lock:
        if osm_thread and osm_thread.is_alive():
            return False
        estado["osm_status"] = "pending"
        estado["osm_error"] = ""
        osm_thread = threading.Thread(target=_cargar_osm_background, daemon=True)
        osm_thread.start()
        return True


def _cargar_osm_background():
    global grafo_global, destinos_global
    estado["osm_status"] = "loading"
    estado["osm_error"] = ""
    try:
        log("OSM en segundo plano: consultando Overpass...")
        osm_patrimonio = get_patrimonio_nacional(max_results=220, max_total_seconds=90)
        if not osm_patrimonio:
            estado["osm_status"] = "error"
            estado["osm_error"] = "OSM sin resultados"
            log("OSM en segundo plano: sin resultados")
            return

        with data_lock:
            base_actual = list(destinos_global)

        merged = _merge_destinos(base_actual, osm_patrimonio)
        if len(merged) == len(base_actual):
            estado["osm_status"] = "ok"
            estado["osm_count"] = len(osm_patrimonio)
            log("OSM en segundo plano: sin cambios en destinos")
            return

        grafo_new = construir_ontologia()
        poblar_grafo(grafo_new, merged)

        with data_lock:
            grafo_global = grafo_new
            destinos_global = merged
            estado["num_destinos"] = len(merged)
            estado["num_tripletas"] = len(grafo_new)

            DATA_FILE.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            Path("data/grafo.ttl").write_text(
                grafo_new.serialize(format="turtle"), encoding="utf-8"
            )

        estado["osm_status"] = "ok"
        estado["osm_count"] = len(osm_patrimonio)
        log(f"OSM en segundo plano: agregados {len(merged) - len(base_actual)} destinos nuevos")
        log("OSM en segundo plano: mapa y cache actualizados; reindexando busqueda semantica")

        ok = indexar_destinos(merged)
        estado["embeddings_ok"] = ok
        estado["osm_count"] = len(osm_patrimonio)
        log("OSM en segundo plano: busqueda semantica actualizada")
    except Exception as e:
        estado["osm_status"] = "error"
        estado["osm_error"] = str(e)
        log(f"OSM en segundo plano: error {e}")


# ── Carga de datos (se ejecuta en hilo separado) ─────────────────────────────

def cargar_datos_background():
    global grafo_global, destinos_global
    estado["cargando"] = True
    estado["log"] = []
    estado["error"] = ""

    try:
        log("Iniciando carga de datos...")

        # 1. Wikidata: destinos para embeddings (fuente semantica principal)
        log("Consultando Wikidata (patrimonio UNESCO)...")
        patrimonio = get_destinos_patrimonio_unesco(limit=25)
        log(f"  → {len(patrimonio)} sitios UNESCO obtenidos")

        log("Consultando Wikidata (museos)...")
        museos = get_museos_espana(limit=30)
        log(f"  → {len(museos)} museos obtenidos")

        log("Consultando Wikidata (destinos generales)...")
        generales = get_destinos_para_embeddings(limit=60)
        if not generales:
            prev_cache = _load_cache_json(DATA_FILE) or []
            generales_prev = [
                d for d in prev_cache
                if d.get("wikidata_id")
                and (d.get("tipo") or "").strip().lower() not in ("museo", "patrimonio_unesco")
            ]
            if generales_prev:
                log(f"  ⚠️ Wikidata devolvio 0. Reutilizando {len(generales_prev)} de cache")
                generales = generales_prev
            else:
                log("  ⚠️ Wikidata devolvio 0 destinos generales")
        log(f"  → {len(generales)} destinos generales obtenidos")

        # 2. OpenStreetMap: patrimonio historico nacional (no bloquear carga principal)
        osm_patrimonio = []
        prev_cache = _load_cache_json(DATA_FILE) or []
        osm_prev = [d for d in prev_cache if d.get("fuente") == "OpenStreetMap"]
        osm_cache_incompleta = 0 < len(osm_prev) < OSM_CACHE_MIN_ITEMS
        if osm_prev:
            log(f"  ⚠️ Reutilizando {len(osm_prev)} OSM desde cache")
            osm_patrimonio = osm_prev
            estado["osm_status"] = "cache"
            estado["osm_count"] = len(osm_prev)
            if osm_cache_incompleta:
                log("  ℹ️ Cache OSM corto: se ampliara en segundo plano")
        else:
            log("  ℹ️ OSM se cargara en segundo plano")
            estado["osm_status"] = "pending"

        # Fusionar y deduplicar por nombre
        destinos_new = _merge_destinos(generales + patrimonio + museos, osm_patrimonio)
        log(f"Total destinos unicos: {len(destinos_new)}")

        # Guardar en disco como cache
        DATA_FILE.write_text(
            json.dumps(destinos_new, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log("Datos guardados en cache (data/destinos.json)")

        # 3. Construir grafo RDF
        log("Construyendo ontologia RDF/OWL...")
        grafo_new = construir_ontologia()
        poblar_grafo(grafo_new, destinos_new)
        num_tripletas = len(grafo_new)
        log(f"Grafo RDF construido: {num_tripletas} tripletas")

        # Serializar el grafo en Turtle
        Path("data/grafo.ttl").write_text(
            grafo_new.serialize(format="turtle"), encoding="utf-8"
        )
        log("Grafo exportado a data/grafo.ttl")

        # 4. Generar embeddings (puede tardar si no hay GPU)
        log("Generando embeddings (puede tardar unos minutos la primera vez)...")
        ok = indexar_destinos(destinos_new)
        estado["embeddings_ok"] = ok
        log(f"Embeddings: {'OK' if ok else 'Usando TF-IDF (instala sentence-transformers)'}")

        # Aplicar cambios al estado global solo si todo fue OK
        with data_lock:
            destinos_global = destinos_new
            grafo_global = grafo_new
            estado["num_destinos"] = len(destinos_new)
            estado["num_tripletas"] = num_tripletas
        estado["cargado"] = True
        log("✅ Carga completa. La aplicacion esta lista.")

        if not osm_prev or osm_cache_incompleta:
            _start_osm_background()
    except Exception as e:
        estado["cargado"] = False
        estado["embeddings_ok"] = False
        estado["error"] = str(e)
        log(f"Error en carga: {e}")
    finally:
        estado["cargando"] = False


# ── Rutas Flask ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/estado")
def api_estado():
    return jsonify(estado)


@app.route("/api/cargar", methods=["POST"])
def api_cargar():
    if estado["cargando"]:
        return jsonify({"ok": False, "msg": "Ya hay una carga en progreso."})

    # Intentar cargar desde caché primero
    body = _json_body()
    forzar = bool(body.get("forzar", False))
    if DATA_FILE.exists() and not forzar:
        global destinos_global, grafo_global
        cache_data = _load_cache_json(DATA_FILE)
        if cache_data is None:
            log("Cache invalida. Forzando recarga completa.")
        else:
            destinos_global = cache_data
            grafo_global = construir_ontologia()
            poblar_grafo(grafo_global, destinos_global)
            Path("data/grafo.ttl").write_text(
                grafo_global.serialize(format="turtle"), encoding="utf-8"
            )
            osm_cached = [d for d in destinos_global if d.get("fuente") == "OpenStreetMap"]
            osm_cache_incompleta = 0 < len(osm_cached) < OSM_CACHE_MIN_ITEMS
            if osm_cached:
                estado["osm_status"] = "cache"
                estado["osm_count"] = len(osm_cached)
            else:
                estado["osm_status"] = "idle"
                estado["osm_count"] = 0
            estado["embeddings_ok"] = indexar_destinos(destinos_global)
            estado["cargado"] = True
            estado["num_destinos"] = len(destinos_global)
            estado["num_tripletas"] = len(grafo_global)
            estado["cargando"] = False
            estado["error"] = ""
            log(f"Datos cargados desde caché ({len(destinos_global)} destinos)")
            if not osm_cached or osm_cache_incompleta:
                log("Cache OSM ausente o corta: completando OpenStreetMap en segundo plano")
                _start_osm_background()
            return jsonify({"ok": True, "msg": "Datos cargados desde caché.", "fuente": "cache"})

    # Carga completa en hilo separado
    t = threading.Thread(target=cargar_datos_background, daemon=True)
    t.start()
    return jsonify({"ok": True, "msg": "Carga iniciada en segundo plano."})


@app.route("/api/destinos")
def api_destinos():
    tipo   = request.args.get("tipo", "")
    limite, err = _int_arg("limite", 1000, min_value=0, max_value=5000)
    if err:
        return jsonify({"error": err}), 400
    with data_lock:
        datos = list(destinos_global)
    if tipo:
        tipo_norm = _normalizar_tipo(tipo)
        if tipo_norm == "destino":
            datos = [d for d in datos if _es_destino_generico(d)]
        else:
            datos = [
                d for d in datos
                if _normalizar_tipo(d.get("tipo", "")) == tipo_norm
                or _normalizar_tipo(d.get("tipo_osm", "")) == tipo_norm
            ]
    if limite > 0:
        datos = datos[:limite]
    # Solo campos necesarios para el mapa
    resultado = [
        {
            "id":          d.get("id", ""),
            "nombre":      d.get("nombre", ""),
            "lat":         d.get("lat", 0),
            "lon":         d.get("lon", 0),
            "tipo":        _tipo_visible(d),
            "descripcion": (d.get("descripcion") or "")[:200],
            "imagen":      d.get("imagen", ""),
        }
        for d in datos
    ]
    return jsonify(resultado)


@app.route("/api/buscar")
def api_buscar():
    query = request.args.get("q", "").strip()
    k, err = _int_arg("k", 8, min_value=1, max_value=50)
    if err:
        return jsonify({"error": err}), 400
    if not query:
        return jsonify({"error": "Parámetro q requerido"}), 400

    if not estado["cargado"]:
        return jsonify({"error": "Datos no cargados aún"}), 503

    # NER sobre la consulta
    ner = extraer_entidades(query)
    # Búsqueda semántica
    resultados = buscar_semantico(query, k=k)
    return jsonify({"resultados": resultados, "ner": ner, "query": query})


@app.route("/api/clima")
def api_clima():
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat y lon requeridos"}), 400
    return jsonify(get_clima(lat, lon))


@app.route("/api/overpass")
def api_overpass():
    ciudad = request.args.get("ciudad", "").strip()
    radio, err = _float_arg("radio", 5.0, min_value=1.0, max_value=20.0)
    if err:
        return jsonify({"error": err}), 400
    if not ciudad:
        return jsonify({"error": "Parámetro ciudad requerido"}), 400
    pois = get_monumentos_ciudad(ciudad, radio_km=radio)
    return jsonify({"ciudad": ciudad, "pois": pois, "total": len(pois)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body     = _json_body()
    pregunta = body.get("pregunta", "").strip()
    if not pregunta:
        return jsonify({"error": "Campo pregunta requerido"}), 400
    if not estado["cargado"]:
        return jsonify({"error": "Datos no cargados. Pulsa 'Cargar datos' primero."}), 503
    result = rag_pipeline(pregunta)
    return jsonify(result)


@app.route("/api/grafo")
def api_grafo():
    with data_lock:
        g = grafo_global
    if g is None:
        return jsonify({"tripletas": [], "total": 0})
    tripletas = grafo_a_json(g)
    return jsonify({"tripletas": tripletas, "total": len(g)})


@app.route("/api/sparql", methods=["GET", "POST"])
def api_sparql():
    if request.method == "POST":
        q = _json_body().get("query", "")
    else:
        q = request.args.get("q", "")

    if not q:
        return jsonify({"error": "Query SPARQL requerida"}), 400
    with data_lock:
        g = grafo_global

    if g is None:
        return jsonify({"error": "Grafo no construido aún"}), 503

    resultados, err = sparql_local(g, q)
    if err:
        return jsonify({"error": f"SPARQL error: {err}"}), 400
    return jsonify({"resultados": resultados, "total": len(resultados)})


@app.route("/api/shacl")
def api_shacl():
    """Devuelve las shapes SHACL definidas en la ontología."""
    return jsonify({"shapes": SHACL_SHAPES})


@app.route("/api/ttl")
def api_ttl():
    """Descarga el grafo en formato Turtle."""
    if grafo_global is None:
        return "Grafo no construido", 503
    ttl = grafo_global.serialize(format="turtle")
    return app.response_class(ttl, mimetype="text/turtle",
                               headers={"Content-Disposition": "attachment;filename=grafo.ttl"})


if __name__ == "__main__":
    print("=" * 60)
    print("  TurismoSemántico — Plataforma de Turismo Inteligente")
    print("  http://localhost:5000")
    print("=" * 60)
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, port=port)
