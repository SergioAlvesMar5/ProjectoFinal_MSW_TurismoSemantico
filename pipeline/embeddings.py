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
import os
import re
import unicodedata
from pathlib import Path

# Desactivar telemetria si el entorno lo permite
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "FALSE")
os.environ.setdefault("POSTHOG_DISABLED", "true")

# Importaciones opcionales con fallback. Se cargan bajo demanda para que Flask
# arranque rapido y sin tocar el indice persistido hasta que haga falta.
SentenceTransformer = None
chromadb = None
EMBEDDINGS_OK = True

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


def _desactivar_embeddings(reason: str) -> None:
    """Activa el modo TF-IDF cuando el stack vectorial falla en runtime."""
    global EMBEDDINGS_OK, _modelo, _chroma_client, _collection
    EMBEDDINGS_OK = False
    _modelo = None
    _chroma_client = None
    _collection = None
    print(f"[Embeddings] {reason}. Usando busqueda TF-IDF.")


def _import_sentence_transformer():
    global SentenceTransformer
    if SentenceTransformer is None and EMBEDDINGS_OK:
        try:
            from sentence_transformers import SentenceTransformer as _SentenceTransformer
            SentenceTransformer = _SentenceTransformer
        except Exception as e:
            _desactivar_embeddings(f"sentence-transformers no disponible ({e})")
            return None
    return SentenceTransformer


def _import_chromadb():
    global chromadb
    if chromadb is None and EMBEDDINGS_OK:
        try:
            import chromadb as _chromadb
            chromadb = _chromadb
        except Exception as e:
            _desactivar_embeddings(f"ChromaDB no disponible ({e})")
            return None
    return chromadb


def _tipo_destino(d: dict) -> str:
    return (d.get("tipo") or d.get("tipo_osm") or "destino").strip() or "destino"


def normalizar_texto_busqueda(texto: str) -> str:
    """Normaliza texto para busquedas: sin acentos, sin mayusculas y con espacios limpios."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.casefold()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _texto_base_destino(d: dict) -> str:
    partes = [
        d.get("texto_embedding", ""),
        d.get("nombre", ""),
        _tipo_destino(d),
        d.get("ciudad", ""),
        d.get("descripcion", ""),
    ]
    return " ".join(str(p).strip() for p in partes if str(p or "").strip())


def _texto_indexable(d: dict) -> str:
    base = _texto_base_destino(d)
    normalizado = normalizar_texto_busqueda(base)
    if normalizado and normalizado not in base.casefold():
        return f"{base}\n{normalizado}"
    return base


def _texto_consulta(query: str) -> str:
    normalizada = normalizar_texto_busqueda(query)
    if normalizada and normalizada != (query or "").casefold():
        return f"{query} {normalizada}"
    return query


def _tokens_busqueda(texto: str) -> set[str]:
    return set(normalizar_texto_busqueda(texto).split())


def _get_modelo():
    global _modelo
    if _modelo is None and EMBEDDINGS_OK:
        try:
            sentence_transformer = _import_sentence_transformer()
            if sentence_transformer is None:
                return None
            print("[Embeddings] Cargando modelo SentenceTransformer...")
            _modelo = sentence_transformer(MODELO_NOMBRE)
        except Exception as e:
            _desactivar_embeddings(f"No se pudo cargar el modelo '{MODELO_NOMBRE}' ({e})")
            return None
    return _modelo


def _get_collection():
    global _chroma_client, _collection
    if _collection is None and EMBEDDINGS_OK:
        try:
            chroma_mod = _import_chromadb()
            if chroma_mod is None:
                return None
            if _chroma_client is None:
                try:
                    from chromadb.config import Settings
                    _chroma_client = chroma_mod.PersistentClient(
                        path="./chroma_db",
                        settings=Settings(anonymized_telemetry=False),
                    )
                except Exception:
                    _chroma_client = chroma_mod.PersistentClient(path="./chroma_db")
            try:
                _collection = _chroma_client.get_collection("destinos")
            except Exception:
                _collection = _chroma_client.create_collection("destinos")
        except Exception as e:
            _desactivar_embeddings(f"No se pudo inicializar ChromaDB ({e})")
            return None
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
    if modelo is None or col is None:
        return False

    # Limpiar colección previa
    try:
        _chroma_client.delete_collection("destinos")
    except Exception:
        pass
    try:
        col = _chroma_client.create_collection("destinos")
    except Exception as e:
        _desactivar_embeddings(f"No se pudo crear la coleccion de ChromaDB ({e})")
        return False
    global _collection
    _collection = col

    textos = [_texto_indexable(d) for d in destinos]
    ids    = [d.get("id", str(i)) for i, d in enumerate(destinos)]

    try:
        print(f"[Embeddings] Generando embeddings para {len(destinos)} destinos...")
        embs = modelo.encode(textos, show_progress_bar=True).tolist()
    except Exception as e:
        _desactivar_embeddings(f"No se pudieron generar embeddings ({e})")
        return False

    # Metadatos para filtrado posterior
    metas = [
        {
            "nombre":     d.get("nombre", ""),
            "lat":        str(d.get("lat", 0)),
            "lon":        str(d.get("lon", 0)),
            "tipo":       _tipo_destino(d),
            "descripcion": (d.get("descripcion") or "")[:500],
        }
        for d in destinos
    ]

    try:
        col.add(ids=ids, documents=textos, embeddings=embs, metadatas=metas)
    except Exception as e:
        _desactivar_embeddings(f"No se pudieron guardar embeddings en ChromaDB ({e})")
        return False

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
    if modelo is None or col is None:
        return _buscar_tfidf(query, k)

    try:
        q_emb = modelo.encode([_texto_consulta(query)]).tolist()
        results = col.query(query_embeddings=q_emb, n_results=k)
    except Exception as e:
        _desactivar_embeddings(f"No se pudo consultar el indice vectorial ({e})")
        return _buscar_tfidf(query, k)

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
    query_words = _tokens_busqueda(query)
    scored = []
    for d in _destinos_cache:
        texto_words = _tokens_busqueda(_texto_base_destino(d))
        # Jaccard simplificado
        intersect = len(query_words & texto_words)
        union     = len(query_words | texto_words)
        score     = intersect / union if union else 0
        if score > 0:
            scored.append({**d, "tipo": _tipo_destino(d), "similitud": round(score, 3)})
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
            f"Tipo: {_tipo_destino(d)}. "
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
    respuesta = _llamar_llm(pregunta, contexto, destinos_relevantes)

    return {
        "pregunta":    pregunta,
        "respuesta":   respuesta,
        "contexto":    contexto,
        "destinos":    destinos_relevantes,
        "entidades":   ner_result.get("entidades", []),
    }


def _respuesta_local_rag(pregunta: str, destinos: list[dict]) -> str:
    """
    Genera una respuesta conversacional usando los destinos recuperados.
    Es el modo local cuando no hay proveedor LLM configurado.
    """
    if not destinos:
        return (
            "No he encontrado coincidencias claras en los datos cargados. "
            "Prueba con una consulta mas concreta, por ejemplo patrimonio UNESCO, "
            "museos, castillos o una zona de Espana."
        )

    pregunta_norm = normalizar_texto_busqueda(pregunta)
    if "museo" in pregunta_norm:
        inicio = "Para museos, las mejores coincidencias que tengo ahora son:"
    elif "unesco" in pregunta_norm or "patrimonio" in pregunta_norm:
        inicio = "Sobre patrimonio cultural, destacaria estas opciones:"
    elif "castillo" in pregunta_norm or "medieval" in pregunta_norm:
        inicio = "Si buscas castillos o lugares con caracter historico, empezaria por:"
    elif "recom" in pregunta_norm or "visitar" in pregunta_norm:
        inicio = "Te recomendaria mirar primero estos destinos:"
    else:
        inicio = "Con los datos semanticos cargados, esto es lo mas relevante que he encontrado:"

    lineas = [inicio]
    for i, d in enumerate(destinos[:3], start=1):
        nombre = d.get("nombre", "Destino sin nombre")
        tipo = _tipo_destino(d)
        desc = (d.get("descripcion") or "").strip()
        if len(desc) > 180:
            desc = desc[:177].rstrip() + "..."
        detalle = f"{i}. {nombre} ({tipo})"
        if desc:
            detalle += f": {desc}"
        lineas.append(detalle)

    lineas.append(
        "La lista sale de la busqueda semantica sobre Wikidata y OpenStreetMap, "
        "asi que puedo afinarla por ciudad, tipo de destino o estilo de viaje."
    )
    return "\n".join(lineas)


def _llamar_llm(pregunta: str, contexto: str, destinos: list[dict]) -> str:
    """
    Llama a la API de Anthropic (claude-haiku) con el contexto RAG.
    Si no hay API key disponible, genera una respuesta local con el contexto recuperado.
    """
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not api_key:
        return _respuesta_local_rag(pregunta, destinos)

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
            model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    except Exception as e:
        print(f"[LLM] Error usando Anthropic: {e}. Respondiendo en modo local.")
        return _respuesta_local_rag(pregunta, destinos)
