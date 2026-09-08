const SVG_NS = "http://www.w3.org/2000/svg";
const DOMAIN_COLOR = { communication: "#46d3ff", financial: "#ffc857", network: "#a78bfa" };

const state = {
  graph: { nodes: [], edges: [] },
  positions: {},
  selectedEntity: null,
  replay: { events: [], index: -1, timer: null },
};

const $ = (id) => document.getElementById(id);
const api = (path) => fetch(path).then((r) => (r.ok ? r.json() : Promise.reject(new Error(path))));
const hhmm = (iso) => new Date(iso).toTimeString().slice(0, 5);
const rupees = (n) => "Rs " + Number(n).toLocaleString("en-IN");

function chip(domain) {
  return `<span class="chip ${domain}">${domain}</span>`;
}

/* ---------------- case header ---------------- */

async function loadCase() {
  const c = await api("/api/case");
  $("case-summary").innerHTML =
    `<b>${c.case_id}</b> · incident ${hhmm(c.incident_time)} +${c.window_minutes}min · ` +
    `${c.totals.cdr} CDR · ${c.totals.ipdr} IPDR · ${c.totals.transactions} transactions · ${c.totals.entities} entities`;
}

/* ---------------- copilot ---------------- */

async function loadLeads() {
  const { leads } = await api("/api/leads?limit=4");
  $("leads").innerHTML = leads
    .map(
      (l) => `
      <article class="lead" data-entity="${l.entity_id}">
        <div class="lead-head">
          <span class="entity">${l.entity_id}</span>
          <span class="confidence">confidence ${l.confidence}%</span>
        </div>
        <div class="chips">${l.domains.map(chip).join("")}</div>
        <p class="hypothesis">${l.hypothesis}</p>
        <h4>Why this matters</h4>
        <ul>${l.why_it_matters.map((w) => `<li>${w}</li>`).join("")}</ul>
        <h4>Recommended next steps</h4>
        <ul>${l.next_steps.map((s) => `<li>${s}</li>`).join("")}</ul>
        <div class="meta">${l.evidence_count} evidence records across ${l.domains.length} dataset${
          l.domains.length > 1 ? "s" : ""
        } · connected: ${
          l.connected_entities.join(", ") || "none"
        }</div>
      </article>`
    )
    .join("");

  document.querySelectorAll(".lead").forEach((el) =>
    el.addEventListener("click", () => selectEntity(el.dataset.entity))
  );
  if (leads.length) selectEntity(leads[0].entity_id);
}

function selectEntity(entityId) {
  state.selectedEntity = entityId;
  document
    .querySelectorAll(".lead")
    .forEach((el) => el.classList.toggle("selected", el.dataset.entity === entityId));
  document
    .querySelectorAll("#graph g.node")
    .forEach((g) => g.classList.toggle("node-active", g.dataset.id === entityId));
  loadReplay(entityId);
}

/* ---------------- graph ---------------- */

async function loadGraph() {
  state.graph = await api("/api/graph");
  const svg = $("graph");
  svg.innerHTML = "";
  const nodes = state.graph.nodes;
  const cx = 320;
  const cy = 230;

  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    const radius = n.risk >= 50 ? 110 : 190;
    state.positions[n.id] = { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  state.graph.edges.forEach((e) => {
    const a = state.positions[e.source];
    const b = state.positions[e.target];
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", a.x);
    line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x);
    line.setAttribute("y2", b.y);
    line.setAttribute("stroke-width", Math.max(1, e.strength / 20));
    line.dataset.source = e.source;
    line.dataset.target = e.target;
    svg.appendChild(line);

    const hit = document.createElementNS(SVG_NS, "line");
    hit.setAttribute("x1", a.x);
    hit.setAttribute("y1", a.y);
    hit.setAttribute("x2", b.x);
    hit.setAttribute("y2", b.y);
    hit.setAttribute("class", "hit");
    hit.addEventListener("click", () => explainEdge(e.source, e.target, line));
    svg.appendChild(hit);
  });

  nodes.forEach((n) => {
    const p = state.positions[n.id];
    const g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("class", "node");
    g.dataset.id = n.id;
    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("cx", p.x);
    circle.setAttribute("cy", p.y);
    circle.setAttribute("r", n.risk >= 50 ? 14 : 8);
    circle.setAttribute("fill", n.risk >= 80 ? "#ff6b6b" : n.risk >= 40 ? "#ffc857" : "#2f3d68");
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", p.x);
    label.setAttribute("y", p.y - (n.risk >= 50 ? 19 : 13));
    label.setAttribute("text-anchor", "middle");
    label.textContent = n.id;
    g.appendChild(circle);
    g.appendChild(label);
    g.addEventListener("click", () => selectEntity(n.id));
    svg.appendChild(g);
  });
}

async function explainEdge(source, target, line) {
  document.querySelectorAll("#graph line").forEach((l) => l.classList.remove("active"));
  line.classList.add("active");
  const r = await api(`/api/relationship?source=${source}&target=${target}`);
  const t = r.temporal_correlation;
  $("edge-explain").classList.remove("empty");
  $("edge-explain").innerHTML = `
    <h3>Why are ${r.source} and ${r.target} connected?</h3>
    <div>Relationship strength <b>${r.strength}%</b></div>
    <div class="strength-bar"><span style="width:${r.strength}%"></span></div>
    <div class="evidence-grid">
      <div class="evidence-card">
        <div class="k">CDR</div>
        <div class="v">${r.communication.calls} calls</div>
        <div class="k">${r.communication.last_contact ? "last " + hhmm(r.communication.last_contact) : "no contact"}</div>
      </div>
      <div class="evidence-card">
        <div class="k">Transactions</div>
        <div class="v">${r.financial.transfers}</div>
        <div class="k">${rupees(r.financial.total_amount)}</div>
      </div>
      <div class="evidence-card">
        <div class="k">IPDR</div>
        <div class="v">${r.network.shared_ips.length} shared</div>
        <div class="k">${r.network.shared_ips.join(", ") || "no shared session"}</div>
      </div>
      <div class="evidence-card">
        <div class="k">Temporal</div>
        <div class="v">${t ? t.records_in_window + " in window" : "—"}</div>
        <div class="k">${t ? "closest " + t.closest_minutes_to_incident + " min from incident" : "outside window"}</div>
      </div>
    </div>
    <div class="chips" style="margin-top:10px">${r.domains.map(chip).join("")}</div>
    <div class="meta">Classification: ${r.classification} · ${r.evidence_count} evidence records</div>`;
}

/* ---------------- incident replay ---------------- */

async function loadReplay(entityId) {
  const { events } = await api(`/api/replay?entity=${entityId}`);
  stopReplay();
  state.replay = { events, index: -1, timer: null };
  $("replay-clock").textContent = "—";
  $("replay-list").innerHTML = events
    .map(
      (e, i) => `<li class="${e.kind}" data-i="${i}">
        <span class="t">${hhmm(e.timestamp)}</span>
        <span><div>${e.title}</div><div class="d">${e.detail} · ${e.record_id}</div></span>
      </li>`
    )
    .join("");
}

function stepReplay() {
  const r = state.replay;
  r.index += 1;
  if (r.index >= r.events.length) return stopReplay(true);
  const e = r.events[r.index];
  $("replay-clock").textContent = hhmm(e.timestamp);
  document.querySelectorAll("#replay-list li").forEach((li) => {
    const i = Number(li.dataset.i);
    li.classList.toggle("shown", i <= r.index);
    li.classList.toggle("current", i === r.index);
  });
  document.querySelectorAll("#graph g.node").forEach((g) => {
    g.classList.toggle("node-active", e.entities.includes(g.dataset.id));
  });
  document.querySelectorAll("#graph line").forEach((l) => {
    const touches = e.entities.includes(l.dataset.source) && e.entities.includes(l.dataset.target);
    l.classList.toggle("active", touches);
  });
  const current = document.querySelector("#replay-list li.current");
  if (current) current.scrollIntoView({ block: "nearest" });
}

function startReplay() {
  if (state.replay.timer) return;
  if (state.replay.index >= state.replay.events.length - 1) resetReplay();
  $("replay-play").textContent = "⏸ Pause";
  state.replay.timer = setInterval(stepReplay, 900);
  stepReplay();
}

function stopReplay(finished = false) {
  clearInterval(state.replay.timer);
  state.replay.timer = null;
  $("replay-play").textContent = finished ? "▶ Replay again" : "▶ Start replay";
}

function resetReplay() {
  stopReplay();
  state.replay.index = -1;
  $("replay-clock").textContent = "—";
  document.querySelectorAll("#replay-list li").forEach((li) => li.classList.remove("shown", "current"));
  document.querySelectorAll("#graph g.node").forEach((g) => g.classList.remove("node-active"));
  document.querySelectorAll("#graph line").forEach((l) => l.classList.remove("active"));
}

/* ---------------- investigation brief ---------------- */

function dnaRows(dna) {
  return Object.entries(dna)
    .map(
      ([k, v]) =>
        `<div class="dna-row"><span>${k}</span><span class="bar"><span style="width:${v}%;background:${
          DOMAIN_COLOR[k] || "#8fa0c4"
        }"></span></span><span>${v}%</span></div>`
    )
    .join("");
}

function briefText(b) {
  const tree = [
    `CASE: ${b.case_id}`,
    ``,
    `PRIMARY ENTITY`,
    `  ${b.primary_entity.entity_id}  ${b.primary_entity.name}  ${b.primary_entity.msisdn}  ${b.primary_entity.account}`,
    ``,
    `ACTIVITY`,
    `  ├── ${b.activity.communications} communications`,
    `  ├── ${b.activity.transactions} financial transactions`,
    `  ├── ${b.activity.ip_sessions} IP sessions`,
    `  └── ${b.activity.connected_entities} connected entities`,
    ``,
    `TIMELINE`,
    ...b.timeline.map((e) => `  ${hhmm(e.timestamp)}  ${e.title}`),
    ``,
    `CORRELATION`,
    ...b.correlation.map(
      (c) => `  ${b.generated_for} ─── ${c.entity_id}   [${c.domains.join(" | ")}]  strength ${c.strength}%`
    ),
    ``,
    `ANOMALIES`,
    ...b.anomalies.map((a) => `  ⚠ ${a.title} — ${a.detail}`),
    ``,
    `INVESTIGATIVE LEAD (confidence ${b.lead.confidence}%, ${b.lead.evidence_count} evidence records)`,
    `  ${b.lead.hypothesis}`,
    ``,
    `WHAT NEXT`,
    ...b.lead.next_steps.map((s, i) => `  ${i + 1}. ${s}`),
    ``,
    b.disclaimer,
  ];
  return tree.join("\n");
}

async function generateBrief() {
  const entity = state.selectedEntity;
  if (!entity) return;
  const b = await api(`/api/brief/${entity}`);
  const best = b.historical_matches[0];
  $("brief").classList.remove("empty");
  $("brief").innerHTML = `
    <pre>${briefText(b)}</pre>
    <h4 style="margin:14px 0 6px">Entity DNA — activity distribution</h4>
    ${dnaRows(b.dna)}
    <h4 style="margin:14px 0 6px">Closest historical case: ${best.case_id} — ${best.label} (${best.match}% match)</h4>
    ${dnaRows(best.dna)}`;
}

/* ---------------- boot ---------------- */

$("replay-play").addEventListener("click", () => (state.replay.timer ? stopReplay() : startReplay()));
$("replay-reset").addEventListener("click", resetReplay);
$("brief-btn").addEventListener("click", generateBrief);

(async function boot() {
  await Promise.all([loadCase(), loadGraph()]);
  await loadLeads();
})();
