"""
pipeline/rdf_model.py
Ontología RDF/OWL del proyecto TurismoSemántico.
Usa rdflib para construir un grafo de conocimiento con clases, propiedades e inferencia.

Tecnologías del curso aplicadas:
  - Práctica 6 (RDF, RDFS, OWL): modelado semántico completo
  - Práctica 8 (SHACL): validación de datos (shapes definidas abajo)
"""

from rdflib import (
    Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL, XSD
)
from rdflib.namespace import SKOS, FOAF
import json
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation

# ── Namespaces ──────────────────────────────────────────────────────────────
TS   = Namespace("http://turismo-semantico.es/ontologia#")
GEO  = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
SCHEMA = Namespace("https://schema.org/")
WD   = Namespace("http://www.wikidata.org/entity/")


def construir_ontologia() -> Graph:
    """
    Define la ontología TurismoSemántico:
      Clases:    Destino, PatrimonioUNESCO, Museo, Castillo, Ciudad, Evento
      Jerarquía: PatrimonioUNESCO ⊂ Destino, Museo ⊂ Destino, etc.
      Props:     nombre, descripcion, latitud, longitud, temperatura,
                 tienePatrimonio, estaEn, tieneEvento
    """
    g = Graph()
    g.bind("ts",     TS)
    g.bind("geo",    GEO)
    g.bind("schema", SCHEMA)
    g.bind("wd",     WD)
    g.bind("owl",    OWL)
    g.bind("skos",   SKOS)

    # ── Declarar ontología ──────────────────────────────────────────────────
    onto = URIRef("http://turismo-semantico.es/ontologia")
    g.add((onto, RDF.type,           OWL.Ontology))
    g.add((onto, RDFS.label,         Literal("TurismoSemántico Ontología", lang="es")))
    g.add((onto, RDFS.comment,       Literal("Ontología para la plataforma de turismo semántico de España", lang="es")))

    # ── Clases ──────────────────────────────────────────────────────────────
    clases = {
        TS.Destino:           "Lugar turístico de España",
        TS.PatrimonioUNESCO:  "Sitio declarado Patrimonio de la Humanidad por la UNESCO",
        TS.Museo:             "Institución que conserva y expone colecciones de valor cultural",
        TS.Castillo:          "Fortaleza o edificación militar histórica",
        TS.Ciudad:            "Núcleo urbano de España",
        TS.Evento:            "Acontecimiento cultural o turístico",
    }
    for cls, comment in clases.items():
        g.add((cls, RDF.type,    OWL.Class))
        g.add((cls, RDFS.label,  Literal(cls.split("#")[-1], lang="es")))
        g.add((cls, RDFS.comment, Literal(comment, lang="es")))

    # ── Jerarquía de clases (rdfs:subClassOf) ───────────────────────────────
    for subclass in [TS.PatrimonioUNESCO, TS.Museo, TS.Castillo]:
        g.add((subclass, RDFS.subClassOf, TS.Destino))

    # ── Propiedades de datos (DatatypeProperty) ─────────────────────────────
    data_props = {
        TS.nombre:       (TS.Destino, XSD.string,  "Nombre del destino"),
        TS.descripcion:  (TS.Destino, XSD.string,  "Descripción del destino"),
        TS.latitud:      (TS.Destino, XSD.decimal, "Latitud geográfica WGS84"),
        TS.longitud:     (TS.Destino, XSD.decimal, "Longitud geográfica WGS84"),
        TS.temperatura:  (TS.Destino, XSD.decimal, "Temperatura actual en grados Celsius"),
        TS.anioPatrimonio: (TS.PatrimonioUNESCO, XSD.gYear, "Año de declaración UNESCO"),
        TS.urlImagen:    (TS.Destino, XSD.anyURI,  "URL de imagen representativa"),
        TS.wikidataId:   (TS.Destino, XSD.string,  "Identificador en Wikidata"),
    }
    for prop, (domain, rng, comment) in data_props.items():
        g.add((prop, RDF.type,      OWL.DatatypeProperty))
        g.add((prop, RDFS.domain,   domain))
        g.add((prop, RDFS.range,    rng))
        g.add((prop, RDFS.comment,  Literal(comment, lang="es")))
        g.add((prop, RDFS.label,    Literal(prop.split("#")[-1], lang="es")))

    # ── Propiedades de objeto (ObjectProperty) ─────────────────────────────
    obj_props = {
        TS.estaEn:          (TS.Destino, TS.Ciudad,  "El destino se ubica en una ciudad"),
        TS.tienePatrimonio: (TS.Ciudad,  TS.Destino, "La ciudad alberga un destino turístico"),
        TS.tieneEvento:     (TS.Destino, TS.Evento,  "El destino acoge un evento"),
        TS.esInversaDe:     (TS.tienePatrimonio, TS.estaEn, "Relación inversa"),
    }
    for prop, (domain, rng, comment) in obj_props.items():
        g.add((prop, RDF.type,     OWL.ObjectProperty))
        g.add((prop, RDFS.domain,  domain))
        g.add((prop, RDFS.range,   rng))
        g.add((prop, RDFS.comment, Literal(comment, lang="es")))

    # Inversa explícita
    g.add((TS.tienePatrimonio, OWL.inverseOf, TS.estaEn))

    return g


def poblar_grafo(g: Graph, destinos: list[dict]) -> Graph:
    """
    Añade instancias al grafo a partir de la lista de destinos.
    """
    def normalize_gyear(value: str | int | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        date_match = re.match(r"^(\d{1,4})(?:-\d{2}-\d{2})?", s)
        if date_match:
            return date_match.group(1).zfill(4)
        if not re.fullmatch(r"-?\d{1,4}", s):
            return None
        if s.startswith("-"):
            return None
        return s.zfill(4)

    def decimal_literal(value) -> Literal:
        try:
            return Literal(Decimal(str(value)), datatype=XSD.decimal)
        except (InvalidOperation, TypeError, ValueError):
            return Literal(str(value), datatype=XSD.decimal)

    TIPO_MAP = {
        "patrimonio_unesco": TS.PatrimonioUNESCO,
        "museo":             TS.Museo,
        "castle":            TS.Castillo,
        "ruins":             TS.Castillo,
        "castillo":          TS.Castillo,
        "ruinas":            TS.Castillo,
        "attraction":        TS.Destino,
    }

    for d in destinos:
        wid = d.get("wikidata_id") or d.get("id", "")
        uri = URIRef(f"http://turismo-semantico.es/destino/{wid}")

        tipo_osm  = (d.get("tipo_osm") or "").strip().lower()
        tipo_wiki = (d.get("tipo") or "").strip().lower()
        cls = TIPO_MAP.get(tipo_osm) or TIPO_MAP.get(tipo_wiki, TS.Destino)

        g.add((uri, RDF.type,       cls))
        g.add((uri, RDF.type,       OWL.NamedIndividual))
        g.add((uri, TS.nombre,      Literal(d["nombre"], lang="es")))
        g.add((uri, TS.latitud,     decimal_literal(d["lat"])))
        g.add((uri, TS.longitud,    decimal_literal(d["lon"])))

        if d.get("descripcion"):
            g.add((uri, TS.descripcion, Literal(d["descripcion"], lang="es")))
        if d.get("imagen"):
            g.add((uri, TS.urlImagen,   Literal(d["imagen"], datatype=XSD.anyURI)))
        if d.get("wikidata_id"):
            g.add((uri, TS.wikidataId,  Literal(d["wikidata_id"])))
            g.add((uri, OWL.sameAs,     WD[d["wikidata_id"]]))
        if d.get("anio_patrimonio"):
            raw_year = d.get("anio_patrimonio")
            norm_year = normalize_gyear(raw_year)
            if norm_year:
                g.add((uri, TS.anioPatrimonio, Literal(norm_year, datatype=XSD.gYear)))
            else:
                g.add((uri, TS.anioPatrimonio, Literal(str(raw_year))))

    return g


def grafo_a_json(g: Graph) -> list[dict]:
    """
    Convierte el grafo a lista de tripletas {sujeto, predicado, objeto}
    para visualización en el frontend.
    """
    triples = []
    for s, p, o in g:
        # Ignorar triples de la ontología; solo instancias
        if "destino/" not in str(s):
            continue
        triples.append({
            "s": str(s).split("/")[-1],
            "p": str(p).split("#")[-1] if "#" in str(p) else str(p).split("/")[-1],
            "o": str(o).split("/")[-1] if str(o).startswith("http") else str(o),
        })
    return triples[:300]  # límite para visualización


def sparql_local(g: Graph, query: str) -> tuple[list[dict], str | None]:
    """
    Ejecuta una consulta SPARQL sobre el grafo local (rdflib).
    Devuelve (resultados, error).
    """
    try:
        results = g.query(query, initNs={"ts": TS, "rdf": RDF, "rdfs": RDFS})
        cols = [str(v) for v in results.vars]
        data = [
            {col: str(row[i]) for i, col in enumerate(cols)}
            for row in results
        ]
        return data, None
    except Exception as e:
        msg = str(e) or "SPARQL error"
        print(f"[SPARQL local] Error: {msg}")
        return [], msg


def validar_shacl(g: Graph) -> dict:
    """
    Valida el grafo con las shapes SHACL del proyecto.
    Usa pySHACL si esta instalado y mantiene un fallback local para la demo.
    """
    try:
        from pyshacl import validate

        shapes_graph = Graph()
        shapes_graph.parse(data=SHACL_SHAPES, format="turtle")
        conforms, _, report_text = validate(
            data_graph=g,
            shacl_graph=shapes_graph,
            inference="rdfs",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
        )
        return {
            "conforms": bool(conforms),
            "engine": "pyshacl",
            "report": str(report_text),
            "violations": [],
        }
    except Exception as e:
        result = _validar_shacl_manual(g)
        result["engine"] = "manual"
        result["warning"] = f"pySHACL no disponible o no ejecutable: {e}"
        return result


def _validar_shacl_manual(g: Graph) -> dict:
    violations = []
    destino_classes = (TS.Destino, TS.PatrimonioUNESCO, TS.Museo, TS.Castillo)
    destinos = set()
    for cls in destino_classes:
        destinos.update(g.subjects(RDF.type, cls))

    def label(uri):
        nombre = next(g.objects(uri, TS.nombre), None)
        return str(nombre) if nombre else str(uri)

    def add_violation(uri, path, message):
        violations.append({
            "focus": label(uri),
            "path": str(path).split("#")[-1],
            "message": message,
        })

    for destino in sorted(destinos, key=str):
        if not list(g.objects(destino, TS.nombre)):
            add_violation(destino, TS.nombre, "Todo destino debe tener un nombre.")
        if not list(g.objects(destino, TS.latitud)):
            add_violation(destino, TS.latitud, "Todo destino debe tener latitud.")
        if not list(g.objects(destino, TS.longitud)):
            add_violation(destino, TS.longitud, "Todo destino debe tener longitud.")

    for destino in sorted(g.subjects(RDF.type, TS.PatrimonioUNESCO), key=str):
        years = list(g.objects(destino, TS.anioPatrimonio))
        if not years:
            add_violation(
                destino,
                TS.anioPatrimonio,
                "El patrimonio UNESCO debe indicar el año de declaración.",
            )
        elif not any(getattr(y, "datatype", None) == XSD.gYear for y in years):
            add_violation(
                destino,
                TS.anioPatrimonio,
                "El año UNESCO debe declararse como xsd:gYear.",
            )

    conforms = not violations
    report = "Conforms: True" if conforms else f"Conforms: False\nViolations: {len(violations)}"
    return {
        "conforms": conforms,
        "report": report,
        "violations": violations,
    }


# ── Shapes SHACL (en Turtle) ────────────────────────────────────────────────
SHACL_SHAPES = """
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix ts:   <http://turismo-semantico.es/ontologia#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

ts:DestinoShape a sh:NodeShape ;
    sh:targetClass ts:Destino ;
    sh:property [
        sh:path ts:nombre ;
        sh:or (
            [ sh:datatype xsd:string ]
            [ sh:datatype rdf:langString ]
        ) ;
        sh:minCount 1 ;
        sh:message "Todo destino debe tener un nombre." ;
    ] ;
    sh:property [
        sh:path ts:latitud ;
        sh:datatype xsd:decimal ;
        sh:minCount 1 ;
        sh:message "Todo destino debe tener latitud." ;
    ] ;
    sh:property [
        sh:path ts:longitud ;
        sh:datatype xsd:decimal ;
        sh:minCount 1 ;
        sh:message "Todo destino debe tener longitud." ;
    ] .

ts:PatrimonioUNESCOShape a sh:NodeShape ;
    sh:targetClass ts:PatrimonioUNESCO ;
    sh:property [
        sh:path ts:anioPatrimonio ;
        sh:datatype xsd:gYear ;
        sh:minCount 1 ;
        sh:message "El patrimonio UNESCO debe indicar el año de declaración." ;
    ] .
"""
