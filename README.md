# TurismoSemántico 🗺️
**Plataforma Inteligente del Patrimonio Cultural de España**

Trabajo Final — Modelado Semántico de la Web

---

## 📦 Fuentes de datos (todas gratuitas, sin API key excepto ANTHROPIC)

| Fuente | URL | Requiere key |
|--------|-----|--------------|
| Wikidata SPARQL | https://query.wikidata.org/sparql | ❌ No |
| OpenStreetMap Overpass | https://overpass-api.de | ❌ No |
| Open-Meteo (clima) | https://api.open-meteo.com | ❌ No |
| Anthropic API (chatbot) | https://api.anthropic.com | ✅ Opcional |

---

## 🚀 Instalación y ejecución

### 1. Crear entorno virtual
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

Para NER con spaCy (opcional pero recomendado):
```bash
python -m spacy download es_core_news_md
```

### 3. (Opcional) Configurar API key de Anthropic para el chatbot
```bash
# Windows:
set ANTHROPIC_API_KEY=tu_api_key_aqui
# Linux/Mac:
export ANTHROPIC_API_KEY=tu_api_key_aqui
```
Sin API key, el chatbot funciona en modo demo mostrando los resultados de la búsqueda semántica.

### 4. Ejecutar la aplicación
```bash
python app.py
```

Abre tu navegador en: **http://localhost:5000**

---

## 🗂️ Estructura del proyecto

```
turismo_semantico/
├── app.py                    ← Servidor Flask (rutas y orquestación)
├── pipeline/
│   ├── __init__.py
│   ├── wikidata.py           ← Consultas SPARQL a Wikidata
│   ├── overpass.py           ← OpenStreetMap Overpass API
│   ├── weather.py            ← Open-Meteo (clima sin key)
│   ├── rdf_model.py          ← Ontología RDF/OWL con rdflib
│   └── embeddings.py         ← ChromaDB + SentenceTransformers + RAG
├── templates/
│   └── index.html            ← Frontend principal
├── static/
│   ├── css/style.css
│   └── js/app.js             ← Leaflet, D3.js, lógica frontend
├── data/                     ← Caché de datos generada automáticamente
└── requirements.txt
```

---

## 🎯 Funcionalidades

1. **Explorador Semántico** — Mapa Leaflet con destinos de Wikidata + OSM
2. **Buscador Semántico** — SentenceTransformers + similitud del coseno
3. **Chatbot RAG** — Pipeline: ChromaDB → contexto → LLM (Claude Haiku)
4. **Grafo RDF** — Visualización D3.js de las tripletas + consola SPARQL local
5. **Clima en tiempo real** — Open-Meteo para cualquier coordenada
6. **POIs OSM** — Consulta Overpass en tiempo real por ciudad

---

## 🔗 Conexión con las prácticas del curso

| Práctica | Tecnología usada en el proyecto |
|----------|--------------------------------|
| P1-P4    | XML/JSON en pipeline de ingesta |
| P5       | Patrón API REST (3 APIs externas) |
| P6       | Ontología RDF/OWL en `rdf_model.py` |
| P7       | SPARQL a Wikidata en `wikidata.py` + consola local |
| P8       | Shapes SHACL definidas en `rdf_model.py` |
| P9       | NER con spaCy en `embeddings.py` |
| P10      | Word Embeddings + similitud coseno |
| P11      | RAG completo: ChromaDB + LLM |
