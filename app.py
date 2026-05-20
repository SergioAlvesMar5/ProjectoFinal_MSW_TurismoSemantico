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
    "log": [],
}
grafo_global = None
destinos_global: list[dict] = []

DATA_FILE = Path("data/destinos.json")
DATA_FILE.parent.mkdir(exist_ok=True)


def log(msg: str):
    print(f"[app] {msg}")
    estado["log"].append(msg)
    if len(estado["log"]) > 50:
        estado["log"] = estado["log"][-50:]


# ── Carga de datos (se ejecuta en hilo separado) ─────────────────────────────

def cargar_datos_background():
    global grafo_global, destinos_global
    estado["cargando"] = True
    estado["log"] = []

    log("Iniciando carga de datos...")

    # 1. Wikidata: destinos para embeddings (fuente semántica principal)
    log("Consultando Wikidata (patrimonio UNESCO)...")
    patrimonio = get_destinos_patrimonio_unesco(limit=25)
    log(f"  → {len(patrimonio)} sitios UNESCO obtenidos")

    log("Consultando Wikidata (museos)...")
    museos = get_museos_espana(limit=30)
    log(f"  → {len(museos)} museos obtenidos")

    log("Consultando Wikidata (destinos generales)...")
    generales = get_destinos_para_embeddings(limit=60)
    log(f"  → {len(generales)} destinos generales obtenidos")

    # 2. OpenStreetMap: patrimonio histórico nacional
    log("Consultando OpenStreetMap (castillos y patrimonio)...")
    osm_patrimonio = get_patrimonio_nacional()
    log(f"  → {len(osm_patrimonio)} elementos patrimoniales de OSM obtenidos")

    # Fusionar y deduplicar por nombre
    todos = {d["nombre"]: d for d in (generales + patrimonio + museos + osm_patrimonio)}
    destinos_global = list(todos.values())
    log(f"Total destinos únicos: {len(destinos_global)}")

    # Guardar en disco como caché
    DATA_FILE.write_text(json.dumps(destinos_global, ensure_ascii=False, indent=2))
    log("Datos guardados en caché (data/destinos.json)")

    # 3. Construir grafo RDF
    log("Construyendo ontología RDF/OWL...")
    grafo_global = construir_ontologia()
    poblar_grafo(grafo_global, destinos_global)
    estado["num_tripletas"] = len(grafo_global)
    log(f"Grafo RDF construido: {estado['num_tripletas']} tripletas")

    # Serializar el grafo en Turtle
    Path("data/grafo.ttl").write_text(
        grafo_global.serialize(format="turtle"), encoding="utf-8"
    )
    log("Grafo exportado a data/grafo.ttl")

    # 4. Generar embeddings (puede tardar si no hay GPU)
    log("Generando embeddings (puede tardar unos minutos la primera vez)...")
    ok = indexar_destinos(destinos_global)
    estado["embeddings_ok"] = ok
    log(f"Embeddings: {'OK' if ok else 'Usando TF-IDF (instala sentence-transformers)'}")

    estado["num_destinos"] = len(destinos_global)
    estado["cargado"]  = True
    estado["cargando"] = False
    log("✅ Carga completa. La aplicación está lista.")


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
    forzar = request.json.get("forzar", False) if request.json else False
    if DATA_FILE.exists() and not forzar:
        global destinos_global, grafo_global
        destinos_global = json.loads(DATA_FILE.read_text())
        grafo_global = construir_ontologia()
        poblar_grafo(grafo_global, destinos_global)
        indexar_destinos(destinos_global)
        estado["cargado"] = True
        estado["num_destinos"] = len(destinos_global)
        estado["num_tripletas"] = len(grafo_global)
        log(f"Datos cargados desde caché ({len(destinos_global)} destinos)")
        return jsonify({"ok": True, "msg": "Datos cargados desde caché.", "fuente": "cache"})

    # Carga completa en hilo separado
    t = threading.Thread(target=cargar_datos_background, daemon=True)
    t.start()
    return jsonify({"ok": True, "msg": "Carga iniciada en segundo plano."})


@app.route("/api/destinos")
def api_destinos():
    tipo   = request.args.get("tipo", "")
    limite = int(request.args.get("limite", 200))
    datos  = destinos_global
    if tipo:
        datos = [d for d in datos if d.get("tipo") == tipo or d.get("tipo_osm") == tipo]
    # Solo campos necesarios para el mapa
    resultado = [
        {
            "id":          d.get("id", ""),
            "nombre":      d.get("nombre", ""),
            "lat":         d.get("lat", 0),
            "lon":         d.get("lon", 0),
            "tipo":        d.get("tipo") or d.get("tipo_osm", ""),
            "descripcion": (d.get("descripcion") or "")[:200],
            "imagen":      d.get("imagen", ""),
        }
        for d in datos[:limite]
    ]
    return jsonify(resultado)


@app.route("/api/buscar")
def api_buscar():
    query = request.args.get("q", "").strip()
    k     = int(request.args.get("k", 8))
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
    radio  = float(request.args.get("radio", 5))
    if not ciudad:
        return jsonify({"error": "Parámetro ciudad requerido"}), 400
    pois = get_monumentos_ciudad(ciudad, radio_km=radio)
    return jsonify({"ciudad": ciudad, "pois": pois, "total": len(pois)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body     = request.json or {}
    pregunta = body.get("pregunta", "").strip()
    if not pregunta:
        return jsonify({"error": "Campo pregunta requerido"}), 400
    if not estado["cargado"]:
        return jsonify({"error": "Datos no cargados. Pulsa 'Cargar datos' primero."}), 503
    result = rag_pipeline(pregunta)
    return jsonify(result)


@app.route("/api/grafo")
def api_grafo():
    if grafo_global is None:
        return jsonify({"tripletas": [], "total": 0})
    tripletas = grafo_a_json(grafo_global)
    return jsonify({"tripletas": tripletas, "total": len(grafo_global)})


@app.route("/api/sparql", methods=["GET", "POST"])
def api_sparql():
    if request.method == "POST":
        q = (request.json or {}).get("query", "")
    else:
        q = request.args.get("q", "")

    if not q:
        return jsonify({"error": "Query SPARQL requerida"}), 400
    if grafo_global is None:
        return jsonify({"error": "Grafo no construido aún"}), 503

    resultados = sparql_local(grafo_global, q)
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
    app.run(debug=True, port=5000)
