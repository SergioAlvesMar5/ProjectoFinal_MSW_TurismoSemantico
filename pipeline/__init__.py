"""pipeline/__init__.py"""

from .wikidata  import get_destinos_patrimonio_unesco, get_museos_espana, get_destinos_para_embeddings
from .overpass  import get_monumentos_ciudad, get_patrimonio_nacional
from .weather   import get_clima
from .rdf_model import construir_ontologia, poblar_grafo, grafo_a_json, sparql_local, validar_shacl, SHACL_SHAPES
from .embeddings import indexar_destinos, buscar_semantico, rag_pipeline, extraer_entidades
