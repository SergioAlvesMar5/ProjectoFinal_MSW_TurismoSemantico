"""
pipeline/embeddings.py
Sistema de búsqueda semántica y RAG (Retrieval-Augmented Generation).

Tecnologías del curso:
  - Práctica 10 (Word Embeddings): SentenceTransformers + similitud coseno
  - Práctica 11 (RAG): ChromaDB + pipeline retrieval → LLM
  - Práctica 9  (NER): spaCy para enriquecer consultas
"""

import json
import math
from pathlib import Path

# Importaciones opcionales con fallback
try:
    from sentence_transformers import SentenceTransformer
    import chromadb
    EMBEDDINGS_OK = True
except Exception as e:
    EMBEDDINGS_OK = False
    print(f"[Embeddings] Embeddings no disponibles ({e}). Usando búsqueda TF-IDF.")

try:
    import spacy
    nlp = spacy.load("es_core_news_md")
    NER_OK = True
except Exception:
    NER_OK = False
    nlp = None


# ── Modelo de embeddings ─────────────────────────────────────────────────────
MODELO_NOMBRE = "paraphrase-multilingual-MiniLM-L12-v2"
_modelo = None
_chroma_client = None
_collection = None
_destinos_cache: list[dict] = []


def _get_modelo():
    global _modelo
    if _modelo is None and EMBEDDINGS_OK:
        print("[Embeddings] Cargando modelo SentenceTransformer...")
        _modelo = SentenceTransformer(MODELO_NOMBRE)
    return _modelo


def _get_collection():
    global _chroma_client, _collection
    if _collection is None and EMBEDDINGS_OK:
        _chroma_client = chromadb.PersistentClient(path="./chroma_db")
        try:
            _collection = _chroma_client.get_collection("destinos")
        except Exception:
            _collection = _chroma_client.create_collection("destinos")
    return _collection


# ── Indexación ───────────────────────────────────────────────────────────────

def indexar_destinos(destinos: list[dict]) -> bool:
    """
    Genera embeddings de todos los destinos y los almacena en ChromaDB.
    Devuelve True si se completó con éxito.
    """
    global _destinos_cache
    _destinos_cache = destinos

    if not EMBEDDINGS_OK:
        print("[Embeddings] Modo TF-IDF activado (sentence-transformers no disponible).")
        return False

    modelo = _get_modelo()
    col    = _get_collection()

    # Limpiar colección previa
    try:
        _chroma_client.delete_collection("destinos")
    except Exception:
        pass
    col = _chroma_client.create_collection("destinos")
    global _collection
    _collection = col

    textos = [d.get("texto_embedding") or d.get("descripcion") or d["nombre"] for d in destinos]
    ids    = [d.get("id", str(i)) for i, d in enumerate(destinos)]

    print(f"[Embeddings] Generando embeddings para {len(destinos)} destinos...")
    embs = modelo.encode(textos, show_progress_bar=True).tolist()

    # Metadatos para filtrado posterior
    metas = [
        {
            "nombre":     d.get("nombre", ""),
            "lat":        str(d.get("lat", 0)),
            "lon":        str(d.get("lon", 0)),
            "tipo":       d.get("tipo", ""),
            "descripcion": (d.get("descripcion") or "")[:500],
        }
        for d in destinos
    ]

    col.add(ids=ids, documents=textos, embeddings=embs, metadatas=metas)
    print(f"[Embeddings] {len(destinos)} destinos indexados en ChromaDB.")
    return True


# ── Búsqueda semántica ───────────────────────────────────────────────────────

def buscar_semantico(query: str, k: int = 5) -> list[dict]:
    """
    Devuelve los k destinos más similares semánticamente a la consulta.
    Si los embeddings no están disponibles, usa TF-IDF de fallback.
    """
    if EMBEDDINGS_OK and _collection is not None:
        return _buscar_con_embeddings(query, k)
    return _buscar_tfidf(query, k)


def _buscar_con_embeddings(query: str, k: int) -> list[dict]:
    modelo = _get_modelo()
    col    = _get_collection()
    if col is None:
        return []

    q_emb = modelo.encode([query]).tolist()
    results = col.query(query_embeddings=q_emb, n_results=k)

    output = []
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        dist = results["distances"][0][i] if results.get("distances") else 0
        output.append({
            "id":          results["ids"][0][i],
            "nombre":      meta.get("nombre", ""),
            "descripcion": meta.get("descripcion", ""),
            "lat":         float(meta.get("lat", 0)),
            "lon":         float(meta.get("lon", 0)),
            "tipo":        meta.get("tipo", ""),
            "similitud":   round(1 - dist, 3),
        })
    return output


def _buscar_tfidf(query: str, k: int) -> list[dict]:
    """Búsqueda TF-IDF simple como fallback (sin dependencias externas)."""
    query_words = set(query.lower().split())
    scored = []
    for d in _destinos_cache:
        texto = (d.get("texto_embedding") or d.get("descripcion") or d["nombre"]).lower()
        texto_words = set(texto.split())
        # Jaccard simplificado
        intersect = len(query_words & texto_words)
        union     = len(query_words | texto_words)
        score     = intersect / union if union else 0
        if score > 0:
            scored.append({**d, "similitud": round(score, 3)})
    scored.sort(key=lambda x: x["similitud"], reverse=True)
    return scored[:k]


# ── NER para enriquecer consultas ────────────────────────────────────────────

def extraer_entidades(texto: str) -> dict:
    """
    Aplica NER con spaCy para identificar lugares, fechas y organizaciones
    en una consulta o descripción turística.
    """
    if not NER_OK or not nlp:
        return {"entidades": [], "ner_disponible": False}

    doc = nlp(texto)
    entidades = [
        {
            "texto": ent.text,
            "tipo":  ent.label_,
            "inicio": ent.start_char,
            "fin":    ent.end_char,
        }
        for ent in doc.ents
    ]
    return {"entidades": entidades, "ner_disponible": True}


# ── RAG: construcción de contexto ────────────────────────────────────────────

def construir_contexto_rag(destinos: list[dict], k: int = 3) -> str:
    """
    Construye el contexto para el LLM a partir de los k destinos más relevantes.
    """
    fragmentos = []
    for d in destinos[:k]:
        fragmentos.append(
            f"Destino: {d.get('nombre', '')}. "
            f"Tipo: {d.get('tipo', '')}. "
            f"Ubicación: lat={d.get('lat','')}, lon={d.get('lon','')}. "
            f"Descripción: {d.get('descripcion', 'Sin descripción disponible.')}."
        )
    return "\n\n".join(fragmentos)


def rag_pipeline(pregunta: str, k: int = 3) -> dict:
    """
    Pipeline RAG completo:
      1. NER sobre la pregunta para enriquecerla
      2. Búsqueda semántica en ChromaDB
      3. Construcción del contexto
      4. Llamada al LLM (Anthropic API)
    Devuelve: respuesta, contexto utilizado, destinos recuperados.
    """
    # Paso 1: NER
    ner_result = extraer_entidades(pregunta)

    # Paso 2: Búsqueda semántica
    destinos_relevantes = buscar_semantico(pregunta, k=k)

    # Paso 3: Contexto
    contexto = construir_contexto_rag(destinos_relevantes, k=k)

    # Paso 4: LLM (Anthropic)
    respuesta = _llamar_llm(pregunta, contexto)

    return {
        "pregunta":    pregunta,
        "respuesta":   respuesta,
        "contexto":    contexto,
        "destinos":    destinos_relevantes,
        "entidades":   ner_result.get("entidades", []),
    }


def _llamar_llm(pregunta: str, contexto: str) -> str:
    """
    Llama a la API de Anthropic (claude-haiku) con el contexto RAG.
    Si no hay API key disponible, genera una respuesta de demostración.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        # Respuesta de demostración basada en el contexto
        if contexto:
            return (
                f"[DEMO sin API key] Basándome en los datos semánticos disponibles, "
                f"he encontrado estos destinos relevantes para tu consulta: "
                f"{', '.join([d['nombre'] for d in buscar_semantico(pregunta, 3)])}. "
                f"Para habilitar respuestas en lenguaje natural, configura ANTHROPIC_API_KEY."
            )
        return "[DEMO] No hay destinos indexados aún. Ejecuta primero la carga de datos."

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Eres un guía turístico experto en el patrimonio cultural y los destinos turísticos de España.
Responde SOLO usando la información del contexto proporcionado.
Si no encuentras la respuesta en el contexto, dilo claramente.
Responde siempre en español, de forma amigable y detallada.

Contexto con información de destinos:
{contexto}

Pregunta del usuario: {pregunta}

Respuesta:"""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    except Exception as e:
        return f"[LLM Error] {e}. Configura ANTHROPIC_API_KEY correctamente."
