/* ══════════════════════════════════════════════════════════
   TurismoSemántico — app.js
   Frontend JavaScript: mapa Leaflet, búsqueda semántica,
   chatbot RAG, visualización del grafo RDF con D3.js
   ══════════════════════════════════════════════════════════ */

"use strict";

// ── Mapa Leaflet ──────────────────────────────────────────────────────────
let mapa = null;
let marcadores = [];
let capas = {};

function iniciarMapa() {
  if (mapa) return;
  mapa = L.map("mapa", { center: [40.4, -3.7], zoom: 6 });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>',
    maxZoom: 18,
  }).addTo(mapa);
}

const ICONOS = {
  patrimonio_unesco: "🏛️",
  museo:             "🖼️",
  castle:            "🏰",
  ruins:             "🏚️",
  attraction:        "⭐",
  default:           "📍",
};

const COLORES = {
  patrimonio_unesco: "#2196F3",
  museo:             "#FF9800",
  castle:            "#9C27B0",
  ruins:             "#795548",
  attraction:        "#4CAF50",
  default:           "#1a5276",
};

function crearIcono(tipo) {
  const emoji = ICONOS[tipo] || ICONOS.default;
  const color  = COLORES[tipo] || COLORES.default;
  return L.divIcon({
    html: `<div style="background:${color};width:28px;height:28px;border-radius:50%;
                       display:flex;align-items:center;justify-content:center;
                       font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,.3);
                       border:2px solid white;">${emoji}</div>`,
    iconSize:   [28, 28],
    iconAnchor: [14, 14],
    className:  "",
  });
}

function cargarMarcadores(destinos) {
  marcadores.forEach(m => mapa.removeLayer(m));
  marcadores = [];
  destinos.forEach(d => {
    if (!d.lat || !d.lon) return;
    const tipo = d.tipo || d.tipo_osm || "";
    const m = L.marker([d.lat, d.lon], { icon: crearIcono(tipo) })
      .addTo(mapa)
      .bindPopup(`
        <div>
          <div class="popup-nombre">${d.nombre}</div>
          <div class="popup-tipo">${tipo || ""}</div>
          ${d.descripcion ? `<p style="font-size:.8rem;margin-top:.4rem">${d.descripcion.substring(0,100)}…</p>` : ""}
          <button onclick="abrirDetalle('${encodeURIComponent(JSON.stringify(d))}')"
            style="margin-top:.5rem;background:#1a5276;color:#fff;border:none;
                   padding:.3rem .8rem;border-radius:6px;cursor:pointer;font-size:.78rem;">
            Ver detalle
          </button>
        </div>
      `);
    marcadores.push(m);
  });
  document.getElementById("statDestinos").textContent = destinos.length;
}

async function filtrarMapa() {
  const tipo = document.getElementById("filtroTipo").value;
  const url  = tipo ? `/api/destinos?tipo=${tipo}` : "/api/destinos";
  const data = await fetch(url).then(r => r.json()).catch(() => []);
  cargarMarcadores(data);
}

async function abrirDetalle(enc) {
  const d = JSON.parse(decodeURIComponent(enc));
  const panel = document.getElementById("panelDetalle");
  const cont  = document.getElementById("detalleContenido");

  cont.innerHTML = `
    <div class="detalle-nombre">${d.nombre}</div>
    <span class="detalle-tipo">${d.tipo || "destino"}</span>
    <div class="detalle-desc">${d.descripcion || "Sin descripción."}</div>
    <div class="clima-mini" id="climaDetalle">🌤️ Cargando clima…</div>
    ${d.imagen ? `<img src="${d.imagen}" alt="${d.nombre}" style="width:100%;border-radius:8px;margin-top:.6rem;max-height:140px;object-fit:cover" loading="lazy"/>` : ""}
  `;
  panel.style.display = "block";

  // Cargar clima
  const clima = await fetch(`/api/clima?lat=${d.lat}&lon=${d.lon}`)
    .then(r => r.json()).catch(() => null);
  if (clima?.temperatura !== null && clima?.temperatura !== undefined) {
    document.getElementById("climaDetalle").innerHTML = `
      ${clima.emoji} <span class="clima-temp">${clima.temperatura}°C</span>
      &nbsp;${clima.descripcion} · 💨 ${clima.viento_kmh} km/h
    `;
  }
}

function cerrarDetalle() {
  document.getElementById("panelDetalle").style.display = "none";
}

async function buscarOSM() {
  const ciudad = document.getElementById("inputCiudadOSM").value.trim();
  if (!ciudad) return;
  const el = document.getElementById("resultadosOSM");
  el.innerHTML = "⏳ Consultando OpenStreetMap…";
  const data = await fetch(`/api/overpass?ciudad=${encodeURIComponent(ciudad)}&radio=5`)
    .then(r => r.json()).catch(() => null);
  if (!data || !data.pois.length) {
    el.innerHTML = "Sin resultados.";
    return;
  }
  el.innerHTML = `<strong>${data.total} POIs encontrados</strong>`;
  data.pois.forEach(p => {
    const div = document.createElement("div");
    div.className = "poi-item";
    div.textContent = `${ICONOS[p.tipo_osm] || "📍"} ${p.nombre}`;
    div.style.cursor = "pointer";
    div.onclick = () => mapa.setView([p.lat, p.lon], 15);
    el.appendChild(div);
  });
  // Añadir marcadores OSM al mapa
  cargarMarcadores([...destinos_cache, ...data.pois]);
}

// ── Carga de datos ────────────────────────────────────────────────────────
let destinos_cache = [];
let estadoPoll = null;

async function cargarDatos(desde_cache = false) {
  document.getElementById("btnCargar").disabled = true;
  document.getElementById("btnCache").disabled  = true;
  const logEl = document.getElementById("logCarga");
  logEl.style.display = "block";
  logEl.textContent   = "Iniciando…\n";

  await fetch("/api/cargar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ forzar: !desde_cache }),
  });

  // Poll de estado
  estadoPoll = setInterval(async () => {
    const est = await fetch("/api/estado").then(r => r.json());
    logEl.textContent = est.log.join("\n");
    logEl.scrollTop   = logEl.scrollHeight;
    actualizarEstadoBadge(est);

    if (est.cargado && !est.cargando) {
      clearInterval(estadoPoll);
      await activarApp();
    }
  }, 1200);
}

async function activarApp() {
  document.getElementById("panelCarga").style.display  = "none";
  document.getElementById("mainContent").style.display = "block";

  iniciarMapa();
  const destinos = await fetch("/api/destinos").then(r => r.json());
  destinos_cache = destinos;
  cargarMarcadores(destinos);

  const est = await fetch("/api/estado").then(r => r.json());
  document.getElementById("statTripletas").textContent = est.num_tripletas;
  actualizarEstadoBadge(est);
}

function actualizarEstadoBadge(est) {
  const icon = document.getElementById("estadoIcon");
  const txt  = document.getElementById("estadoTexto");
  if (est.cargando) {
    icon.textContent = "⏳";
    txt.textContent  = "Cargando…";
  } else if (est.cargado) {
    icon.textContent = "✅";
    txt.textContent  = `${est.num_destinos} destinos · ${est.num_tripletas} tripletas`;
  } else {
    icon.textContent = "⚪";
    txt.textContent  = "Sin datos";
  }
}

// ── Navegación ────────────────────────────────────────────────────────────
function mostrarSeccion(id) {
  document.querySelectorAll(".seccion").forEach(s => s.classList.remove("activa"));
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));

  document.getElementById("sec" + id.charAt(0).toUpperCase() + id.slice(1))
    ?.classList.add("activa");

  const navMap = { mapa:"Explorar", buscar:"Buscar", chat:"Guía IA", grafo:"Grafo RDF", sparql:"SPARQL" };
  document.querySelectorAll(".nav-btn").forEach(b => {
    if (b.textContent.includes(navMap[id])) b.classList.add("active");
  });

  // Invalidar tamaño del mapa al mostrar
  if (id === "mapa" && mapa) setTimeout(() => mapa.invalidateSize(), 100);
  if (id === "grafo") cargarGrafo();
}

// ── Búsqueda semántica ────────────────────────────────────────────────────
async function ejecutarBusqueda() {
  const q = document.getElementById("inputBuscar").value.trim();
  if (!q) return;
  const resCont = document.getElementById("resultadosBusqueda");
  resCont.innerHTML = `<p class="msg-loading">🔍 Buscando…</p>`;

  const data = await fetch(`/api/buscar?q=${encodeURIComponent(q)}&k=9`)
    .then(r => r.json()).catch(() => null);

  if (!data) { resCont.innerHTML = `<p class="msg-error">Error de conexión.</p>`; return; }

  // Mostrar entidades NER
  const nerEl = document.getElementById("nerResultados");
  const nerTags = document.getElementById("nerTags");
  if (data.ner?.entidades?.length) {
    nerTags.innerHTML = data.ner.entidades
      .map(e => `<span class="ner-tag">${e.texto} <small>${e.tipo}</small></span>`)
      .join("");
    nerEl.style.display = "block";
  } else {
    nerEl.style.display = "none";
  }

  if (!data.resultados?.length) {
    resCont.innerHTML = `<p class="msg-loading">Sin resultados para "${q}".</p>`;
    return;
  }

  resCont.innerHTML = data.resultados.map(r => `
    <div class="resultado-card" onclick="irADestino(${r.lat},${r.lon},'${r.nombre}')"
         role="listitem" tabindex="0" aria-label="${r.nombre}">
      <div class="res-nombre">${r.nombre}</div>
      <div class="res-tipo">${ICONOS[r.tipo] || "📍"} ${r.tipo || "destino"}</div>
      <div class="res-desc">${r.descripcion || "Sin descripción."}</div>
      <div class="res-sim">Similitud: ${Math.round((r.similitud||0)*100)}%</div>
      <div class="sim-bar"><div class="sim-fill" style="width:${Math.round((r.similitud||0)*100)}%"></div></div>
    </div>
  `).join("");
}

function buscarEjemplo(q) {
  document.getElementById("inputBuscar").value = q;
  ejecutarBusqueda();
}

function irADestino(lat, lon, nombre) {
  mostrarSeccion("mapa");
  setTimeout(() => {
    mapa.setView([lat, lon], 12);
    marcadores.forEach(m => {
      if (m.getPopup()?.getContent()?.includes(nombre)) m.openPopup();
    });
  }, 150);
}

// ── Chatbot RAG ───────────────────────────────────────────────────────────
async function enviarChat() {
  const input = document.getElementById("inputChat");
  const q     = input.value.trim();
  if (!q) return;
  input.value = "";
  agregarMensaje("user", q);
  const typingId = agregarMensaje("bot", "⏳ Consultando grafo semántico…", "typing");

  const data = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pregunta: q }),
  }).then(r => r.json()).catch(() => null);

  // Eliminar "typing"
  document.getElementById(typingId)?.remove();

  if (!data) { agregarMensaje("bot", "❌ Error de conexión."); return; }

  let contenido = data.respuesta || "No tengo respuesta.";
  if (data.destinos?.length) {
    contenido += `<div class="msg-fuentes">📍 Fuentes: ${data.destinos.map(d => d.nombre).join(", ")}</div>`;
  }
  agregarMensaje("bot", contenido);
}

function agregarMensaje(tipo, texto, cls = "") {
  const cont = document.getElementById("chatContenedor");
  const id   = "msg_" + Date.now();
  const div  = document.createElement("div");
  div.id = id;
  div.className = tipo === "bot" ? "msg-bot" : "msg-user";
  div.innerHTML = `
    <span class="msg-avatar">${tipo === "bot" ? "🤖" : "👤"}</span>
    <div class="msg-burbuja ${cls}">${texto}</div>
  `;
  cont.appendChild(div);
  cont.scrollTop = cont.scrollHeight;
  return id;
}

function preguntarChat(q) {
  document.getElementById("inputChat").value = q;
  enviarChat();
}

// ── Grafo RDF (D3.js) ─────────────────────────────────────────────────────
async function cargarGrafo() {
  const cont = document.getElementById("grafoVisualizacion");
  cont.innerHTML = "<p class='msg-loading' style='padding:1rem'>Cargando grafo…</p>";

  const data = await fetch("/api/grafo").then(r => r.json()).catch(() => null);
  if (!data?.tripletas?.length) {
    cont.innerHTML = "<p class='msg-loading' style='padding:1rem'>Grafo no disponible. Carga datos primero.</p>";
    return;
  }

  document.getElementById("grafoStats").textContent =
    `${data.total} tripletas totales · Mostrando muestra de ${data.tripletas.length}`;

  renderGrafoD3(cont, data.tripletas.slice(0, 80));
  renderTripletasTabla(data.tripletas);
}

function renderGrafoD3(container, tripletas) {
  container.innerHTML = "";
  const W = container.clientWidth || 800;
  const H = Math.max(container.clientHeight || 320, 320);

  // Construir nodos y enlaces
  const nodosMap = {};
  const enlaces  = [];
  const relMap   = new Map();

  tripletas.forEach(t => {
    [t.s, t.o].forEach(id => { if (!nodosMap[id]) nodosMap[id] = { id }; });
    enlaces.push({ source: t.s, target: t.o, label: t.p });
    if (!relMap.has(t.s)) relMap.set(t.s, []);
    if (!relMap.has(t.o)) relMap.set(t.o, []);
    relMap.get(t.s).push({ dir: "->", p: t.p, other: t.o });
    relMap.get(t.o).push({ dir: "<-", p: t.p, other: t.s });
  });
  const nodos = Object.values(nodosMap);

  const detalleEl = document.getElementById("grafoDetalle");
  const maxRels = 8;
  const tooltip = document.createElement("div");
  tooltip.className = "grafo-tooltip";
  tooltip.setAttribute("aria-hidden", "true");
  tooltip.innerHTML = "<div class=\"grafo-tooltip-title\">Detalle del nodo</div>" +
    "<div class=\"grafo-tooltip-meta\">Haz clic en una burbuja.</div>";

  function inferNodeType(id) {
    const lower = String(id || "").toLowerCase();
    if (lower.includes("unesco") || lower.includes("patrimonio")) return "Patrimonio UNESCO";
    if (lower.includes("museo")) return "Museo";
    if (lower.includes("castillo") || lower.includes("castle")) return "Castillo";
    if (lower.includes("destino")) return "Destino";
    if (lower.startsWith("http")) return "URI";
    if (/^q\d+$/i.test(lower)) return "Wikidata";
    return "Entidad";
  }

  function getTopPredicates(rels, limit = 4) {
    const counts = new Map();
    rels.forEach(r => counts.set(r.p, (counts.get(r.p) || 0) + 1));
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit);
  }

  function hideTooltip() {
    tooltip.classList.remove("visible");
    tooltip.setAttribute("aria-hidden", "true");
  }

  function showTooltip(id, rels) {
    const total = rels.length;
    const outgoing = rels.filter(r => r.dir === "->").length;
    const incoming = total - outgoing;
    const tipo = inferNodeType(id);
    const topPreds = getTopPredicates(rels, 4);
    const ejemplos = rels.slice(0, 3);

    tooltip.innerHTML = `
      <div class="grafo-tooltip-title">${id}</div>
      <div class="grafo-tooltip-meta">${tipo}${total ? " · " + total + " relaciones" : ""}</div>
      ${total ? `
        <div class="gt-row">
          <span class="gt-label">Salientes:</span> ${outgoing}
          <span class="gt-dot">•</span>
          <span class="gt-label">Entrantes:</span> ${incoming}
        </div>
      ` : `<div class="gt-row">Sin relaciones visibles en esta muestra.</div>`}
      ${topPreds.length ? `
        <div class="gt-subtitle">Predicados frecuentes</div>
        <div class="gt-chips">
          ${topPreds.map(([p, c]) => `<span class="gt-chip">${p} (${c})</span>`).join("")}
        </div>
      ` : ""}
      ${ejemplos.length ? `
        <div class="gt-subtitle">Ejemplos</div>
        <div class="gt-list">
          ${ejemplos.map(r => `<div>${r.dir} ${r.other}</div>`).join("")}
        </div>
      ` : ""}
    `;
    tooltip.classList.add("visible");
    tooltip.setAttribute("aria-hidden", "false");
  }

  function resetDetalle() {
    if (!detalleEl) return;
    detalleEl.innerHTML = "";
    const title = document.createElement("h4");
    title.textContent = "Detalle del nodo";
    const meta = document.createElement("div");
    meta.className = "grafo-detalle-meta";
    meta.textContent = "Haz clic en una burbuja para ver sus relaciones.";
    detalleEl.append(title, meta);
    hideTooltip();
  }

  function renderDetalle(id) {
    if (!detalleEl) return;
    const rels = relMap.get(id) || [];
    detalleEl.innerHTML = "";

    const title = document.createElement("h4");
    title.textContent = "Detalle del nodo";
    const nombre = document.createElement("div");
    nombre.className = "grafo-detalle-nombre";
    nombre.textContent = id;
    const meta = document.createElement("div");
    meta.className = "grafo-detalle-meta";
    meta.textContent = `Relaciones visibles: ${rels.length}`;
    detalleEl.append(title, nombre, meta);

    if (!rels.length) {
      const empty = document.createElement("div");
      empty.className = "grafo-detalle-meta";
      empty.textContent = "Sin relaciones en esta vista.";
      detalleEl.appendChild(empty);
      showTooltip(id, rels);
      return;
    }

    const ul = document.createElement("ul");
    rels.slice(0, maxRels).forEach(r => {
      const li = document.createElement("li");
      const dir = document.createElement("span");
      dir.className = "g-rel";
      dir.textContent = `${r.dir} `;
      const pred = document.createElement("span");
      pred.className = "g-p";
      pred.textContent = `${r.p} `;
      const obj = document.createElement("span");
      obj.className = "g-o";
      obj.textContent = r.other;
      li.append(dir, pred, obj);
      ul.appendChild(li);
    });
    detalleEl.appendChild(ul);

    if (rels.length > maxRels) {
      const more = document.createElement("div");
      more.className = "grafo-detalle-meta";
      more.textContent = `+ ${rels.length - maxRels} relaciones mas`;
      detalleEl.appendChild(more);
    }
    showTooltip(id, rels);
  }

  const svg = d3.select(container).append("svg")
    .attr("viewBox", `0 0 ${W} ${H}`)
    .attr("width", "100%").attr("height", "100%");

  container.appendChild(tooltip);

  resetDetalle();

  const g = svg.append("g").attr("class", "grafo-canvas");

  const zoom = d3.zoom()
    .scaleExtent([0.3, 3])
    .on("zoom", (event) => { g.attr("transform", event.transform); });
  svg.call(zoom);

  const sim = d3.forceSimulation(nodos)
    .force("link",   d3.forceLink(enlaces).id(d => d.id).distance(60))
    .force("charge", d3.forceManyBody().strength(-80))
    .force("center", d3.forceCenter(W/2, H/2));

  const link = g.append("g")
    .selectAll("line").data(enlaces).enter().append("line")
    .attr("class", "grafo-link");

  const nodeColor = d => {
    const id = d.id.toLowerCase();
    if (id.includes("patrimonio") || id.includes("unesco")) return "#2196F3";
    if (id.includes("museo"))   return "#FF9800";
    if (id.includes("castillo") || id.includes("castle")) return "#9C27B0";
    return "#4CAF50";
  };

  const node = g.append("g")
    .selectAll("circle").data(nodos).enter().append("circle")
    .attr("r", 6).attr("fill", nodeColor).attr("stroke", "#fff").attr("stroke-width", 1.5)
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", (e, d) => {
        if (e.sourceEvent) e.sourceEvent.stopPropagation();
        if (!e.active) sim.alphaTarget(0.3).restart();
        d.fx = d.x; d.fy = d.y;
      })
      .on("drag",  (e, d) => {
        if (e.sourceEvent) e.sourceEvent.stopPropagation();
        d.fx = e.x; d.fy = e.y;
      })
      .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }));

  node.on("click", (e, d) => {
    e.stopPropagation();
    node.classed("grafo-node-active", n => n.id === d.id);
    link.classed("grafo-link-active", l => {
      const sId = l.source?.id || l.source;
      const tId = l.target?.id || l.target;
      return sId === d.id || tId === d.id;
    });
    renderDetalle(d.id);
  });

  node.append("title").text(d => d.id);

  const label = g.append("g")
    .selectAll("text").data(nodos).enter().append("text")
    .text(d => d.id.substring(0,18))
    .attr("font-size", 8).attr("fill", "var(--c-text-sec)")
    .attr("dx", 9).attr("dy", 3)
    .attr("pointer-events", "none");

  svg.on("click", () => {
    node.classed("grafo-node-active", false);
    link.classed("grafo-link-active", false);
    resetDetalle();
  });

  sim.on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("cx", d => d.x).attr("cy", d => d.y);
    label.attr("x", d => d.x).attr("y", d => d.y);
  });
}

function renderTripletasTabla(tripletas) {
  const cont = document.getElementById("tripletasTabla");
  cont.innerHTML = `
    <div class="tripletas-scroll">
    <table>
      <thead><tr><th>Sujeto</th><th>Predicado</th><th>Objeto</th></tr></thead>
      <tbody>
        ${tripletas.slice(0, 100).map(t => `
          <tr>
            <td class="t-s">${t.s}</td>
            <td class="t-p">${t.p}</td>
            <td class="t-o">${t.o}</td>
          </tr>`).join("")}
      </tbody>
    </table>
    </div>`;
}

// ── SPARQL local ──────────────────────────────────────────────────────────
const EJEMPLOS_SPARQL = {
  todos_destinos: `PREFIX ts: <http://turismo-semantico.es/ontologia#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?nombre ?lat ?lon WHERE {
  ?destino rdf:type ?tipo ;
           ts:nombre ?nombre ;
           ts:latitud ?lat ;
           ts:longitud ?lon .
  ?tipo rdfs:subClassOf* ts:Destino .
}
LIMIT 20`,

  patrimonio_unesco: `PREFIX ts: <http://turismo-semantico.es/ontologia#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?nombre ?lat ?lon WHERE {
  ?destino rdf:type ts:PatrimonioUNESCO ;
           ts:nombre ?nombre ;
           ts:latitud ?lat ;
           ts:longitud ?lon .
}`,

  museos: `PREFIX ts: <http://turismo-semantico.es/ontologia#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?nombre ?lat ?lon WHERE {
  ?destino rdf:type ts:Museo ;
           ts:nombre ?nombre ;
           ts:latitud ?lat ;
           ts:longitud ?lon .
}`,

  contar_tipos: `PREFIX ts: <http://turismo-semantico.es/ontologia#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?tipo (COUNT(?d) AS ?total) WHERE {
  ?d rdf:type ?tipo .
  FILTER(STRSTARTS(STR(?tipo), "http://turismo-semantico.es"))
}
GROUP BY ?tipo
ORDER BY DESC(?total)`,
};

function cargarEjemploSparql(clave) {
  document.getElementById("sparqlQuery").value = EJEMPLOS_SPARQL[clave] || "";
}

async function ejecutarSparql() {
  const q    = document.getElementById("sparqlQuery").value.trim();
  const cont = document.getElementById("sparqlResultados");
  cont.innerHTML = `<p class="msg-loading">⏳ Ejecutando…</p>`;

  const data = await fetch("/api/sparql", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ query: q }),
  }).then(r => r.json()).catch(() => null);

  if (!data) { cont.innerHTML = `<p class="msg-error">Error de conexión.</p>`; return; }
  if (data.error) { cont.innerHTML = `<p class="msg-error">${data.error}</p>`; return; }
  if (!data.resultados?.length) { cont.innerHTML = `<p class="msg-loading">Sin resultados.</p>`; return; }

  const cols = Object.keys(data.resultados[0]);
  cont.innerHTML = `
    <p style="font-size:.8rem;color:#555;margin-bottom:.5rem">${data.total} resultados</p>
    <table class="sparql-table">
      <thead><tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr></thead>
      <tbody>
        ${data.resultados.map(r =>
          `<tr>${cols.map(c => `<td>${r[c] || ""}</td>`).join("")}</tr>`
        ).join("")}
      </tbody>
    </table>`;
}

// ── Tema claro/oscuro ────────────────────────────────────────────────────
function getSystemTheme() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

let themeTransitionTimer = null;

function runThemeTransition() {
  const root = document.documentElement;
  root.classList.add("theme-transition");
  if (themeTransitionTimer) window.clearTimeout(themeTransitionTimer);
  themeTransitionTimer = window.setTimeout(() => {
    root.classList.remove("theme-transition");
    themeTransitionTimer = null;
  }, 300);
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "dark" || theme === "light") {
    root.setAttribute("data-theme", theme);
  } else {
    root.removeAttribute("data-theme");
  }
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  const isDark = (root.getAttribute("data-theme") || getSystemTheme()) === "dark";
  btn.textContent = isDark ? "☀️" : "🌙";
  btn.setAttribute("aria-label", isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
  btn.setAttribute("title", isDark ? "Modo claro" : "Modo oscuro");
  btn.setAttribute("aria-pressed", isDark ? "true" : "false");
}

function initThemeToggle() {
  const saved = localStorage.getItem("theme");
  const initial = saved === "dark" || saved === "light" ? saved : getSystemTheme();
  applyTheme(initial);

  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || getSystemTheme();
    const next = current === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    runThemeTransition();
    applyTheme(next);
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (localStorage.getItem("theme")) return;
    runThemeTransition();
    applyTheme(e.matches ? "dark" : "light");
  });
}

// ── Inicialización ────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  initThemeToggle();
  // Comprobar si ya hay datos en caché
  const est = await fetch("/api/estado").then(r => r.json()).catch(() => null);
  if (est?.cargado) {
    await activarApp();
  }
  // Poll de estado periódico si está cargando
  if (est?.cargando) {
    estadoPoll = setInterval(async () => {
      const e2 = await fetch("/api/estado").then(r => r.json());
      if (e2.cargado && !e2.cargando) { clearInterval(estadoPoll); await activarApp(); }
      actualizarEstadoBadge(e2);
    }, 1200);
  }
});
