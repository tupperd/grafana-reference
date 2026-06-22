const $ = (sel) => document.querySelector(sel);

// Per-thread chat state. history = [{role, content}] of completed turns.
const threads = {
  outfit: { conversationId: null, history: [] },
  shopping: { conversationId: null, history: [] },
};
let mode = "outfit";

const MODE = {
  outfit: {
    path: "/api/outfit/chat",
    field: "occasion",
    agent: "outfit-builder",
    desc: "The Stylist composes a look from your closet, with palette-analyst, occasion-decoder & silhouette-planner researching on its behalf.",
    placeholder: "Describe the occasion — e.g. dinner date, office, weekend",
    empty: "Ask the stylist to compose a look for any occasion.",
  },
  shopping: {
    path: "/api/shopping/chat",
    field: "goal",
    agent: "shopping-assistant",
    desc: "The Buyer sources the additions that complete your wardrobe, with gap-auditor, trend-advisor & value-strategist researching on its behalf.",
    placeholder: "Describe the brief — e.g. build a capsule wardrobe for fall",
    empty: "Tell the buyer your goal and it will recommend what to add.",
  },
};

// --- helpers ---------------------------------------------------------------
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (res.status === 401) { showLogin(); throw new Error("Not authenticated"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function showLogin() { $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); }
function showApp() { $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); }

// --- Auth ------------------------------------------------------------------
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#username").value, password: $("#password").value }),
    });
    await boot();
  } catch (err) { $("#login-error").textContent = err.message; }
});

$("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  showLogin();
});

// --- Catalog ---------------------------------------------------------------
const TYPE_MONOGRAM = { top: "T", bottom: "B", outerwear: "O", shoes: "S", accessory: "A" };
const COLOR_HEX = {
  white: "#f4f1ea", cream: "#efe6d2", ivory: "#f2ead7", beige: "#d8c7a8", tan: "#c2a16b",
  khaki: "#b3a06b", grey: "#8d877c", gray: "#8d877c", charcoal: "#3a3a3c", black: "#211d18",
  navy: "#26334d", indigo: "#34406b", blue: "#3b5b8c", "light blue": "#9db8d6",
  olive: "#6b6b3a", green: "#3f6b46", brown: "#6f4e34", red: "#9a2d2d", burgundy: "#5e2230",
  pink: "#d68fa0", purple: "#6b4a7a", yellow: "#d9b84a", orange: "#c0431b",
};
function colorHex(name) {
  const c = String(name || "").toLowerCase().trim();
  if (COLOR_HEX[c]) return COLOR_HEX[c];
  for (const k in COLOR_HEX) if (c.includes(k)) return COLOR_HEX[k];
  return "#b8ab95";
}
const pad = (n) => String(n).padStart(2, "0");

$("#toggle-add").addEventListener("click", () => $("#add-form").classList.toggle("hidden"));

async function loadCatalog() {
  const items = await api("/api/items");
  $("#item-count").textContent = `${items.length} pieces`;
  const grid = $("#catalog");
  grid.innerHTML = "";
  items.forEach((it, i) => {
    const el = document.createElement("article");
    el.className = "garment";
    el.style.animationDelay = `${Math.min(i, 14) * 45}ms`;
    const attrs = ["type", "season", "formality", "material"]
      .filter((k) => it[k])
      .map((k) => `<span class="attr">${escapeHtml(it[k])}</span>`)
      .join("");
    el.innerHTML = `
      <button class="del" title="Remove" data-id="${it.id}">✕</button>
      <div class="garment-top">
        <span class="cat-no">Nº ${pad(it.id)}</span>
        <span class="monogram">${TYPE_MONOGRAM[it.type] || "·"}</span>
      </div>
      <h3 class="garment-name">${escapeHtml(it.name)}</h3>
      <div class="swatch"><span class="dot" style="background:${colorHex(it.color)}"></span>${escapeHtml(it.color || "—")}</div>
      <div class="attrs">${attrs}</div>`;
    grid.appendChild(el);
  });
  grid.querySelectorAll(".del").forEach((b) =>
    b.addEventListener("click", async () => {
      await api(`/api/items/${b.dataset.id}`, { method: "DELETE" });
      loadCatalog();
    })
  );
}

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target).entries());
  await api("/api/items", { method: "POST", body: JSON.stringify(body) });
  e.target.reset();
  loadCatalog();
});

// --- Chat: mode switching --------------------------------------------------
function threadEl(m) { return $(`#thread-${m}`); }

function applyMode() {
  const cfg = MODE[mode];
  document.querySelectorAll("#mode-seg .seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode)
  );
  $("#mode-desc").textContent = cfg.desc;
  $("#composer-input").placeholder = cfg.placeholder;
  threadEl("outfit").classList.toggle("hidden", mode !== "outfit");
  threadEl("shopping").classList.toggle("hidden", mode !== "shopping");
  ensureEmptyState(mode);
  scrollChat();
}

function ensureEmptyState(m) {
  const el = threadEl(m);
  if (threads[m].history.length === 0 && !el.querySelector(".bubble")) {
    el.innerHTML = `<div class="empty">${MODE[m].empty}</div>`;
  }
}

document.querySelectorAll("#mode-seg .seg").forEach((b) =>
  b.addEventListener("click", () => { mode = b.dataset.mode; applyMode(); })
);

function scrollChat() {
  const c = $("#chat");
  c.scrollTop = c.scrollHeight;
}

// --- Chat: sending a turn --------------------------------------------------
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); sendTurn(); });

function bubble(thread, role) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  thread.appendChild(el);
  return el;
}

async function sendTurn() {
  const text = $("#composer-input").value.trim();
  if (!text) return;
  const m = mode;
  const t = threads[m];
  const cfg = MODE[m];
  const thread = threadEl(m);

  // clear empty-state on first message
  const empty = thread.querySelector(".empty");
  if (empty) empty.remove();

  // user bubble
  bubble(thread, "user").textContent = text;

  // assistant placeholder
  const a = bubble(thread, "assistant");
  a.innerHTML = `<div class="developing">${m === "outfit" ? "The stylist is composing" : "The buyer is sourcing"}</div>`;
  $("#composer-input").value = "";
  $("#composer-send").disabled = true;
  scrollChat();

  const firstTurn = t.history.length === 0;
  const runResearch = firstTurn || $("#deep-research").checked;

  try {
    const payload = {
      conversation_id: t.conversationId || "",
      [cfg.field]: text,
      history: t.history,
      run_research: runResearch,
    };
    const data = await api(cfg.path, { method: "POST", body: JSON.stringify(payload) });
    t.conversationId = data.conversation_id;
    t.history.push({ role: "user", content: text });
    t.history.push({ role: "assistant", content: data.reply || "" });
    renderTurn(m, a, data);
  } catch (err) {
    a.innerHTML = `<div class="error" style="text-align:left">${escapeHtml(err.message)}</div>`;
  } finally {
    $("#composer-send").disabled = false;
    scrollChat();
  }
}

function proposalHtml(kind, data) {
  const p = data.proposal;
  if (!p) return "";
  if (kind === "outfit") {
    const look = (data.chosen_items || [])
      .map((it) => `<li><span class="look-name">${escapeHtml(it.name)}</span><span class="look-type">${escapeHtml(it.type || "")}</span></li>`)
      .join("");
    return `
      ${p.title ? `<div class="proposal-title">${escapeHtml(p.title)}</div>` : ""}
      ${look ? `<ol class="look">${look}</ol>` : ""}
      ${p.rationale ? `<blockquote class="pull">${escapeHtml(p.rationale)}</blockquote>` : ""}
      ${p.styling_tips ? `<p class="footnote"><b>Styling note —</b> ${escapeHtml(p.styling_tips)}</p>` : ""}`;
  }
  const entries = (p.recommendations || [])
    .map((x) => `<div class="entry">
        ${x.category ? `<span class="entry-cat">${escapeHtml(x.category)}</span>` : ""}
        <h4>${escapeHtml(x.item || "")}</h4>
        <p>${escapeHtml(x.reason || "")}</p>
        ${x.pairs_with ? `<span class="pairs">Pairs with ${escapeHtml(x.pairs_with)}</span>` : ""}
      </div>`)
    .join("");
  return `
    ${p.summary ? `<blockquote class="pull">${escapeHtml(p.summary)}</blockquote>` : ""}
    <div class="entries">${entries}</div>`;
}

function researchHtml(research) {
  if (!research || !research.length) return "";
  const notes = research
    .map((r) => `<div class="note"><div class="note-agent">${escapeHtml(r.agent)}</div><div>${escapeHtml(r.note)}</div></div>`)
    .join("");
  return `<details class="research"><summary>Research notes · ${research.length} sub-agents</summary>${notes}</details>`;
}

function renderTurn(kind, el, data) {
  const turnNo = Math.ceil(threads[kind].history.length / 2);
  el.innerHTML = `
    ${data.reply ? `<div class="reply">${escapeHtml(data.reply)}</div>` : ""}
    ${proposalHtml(kind, data)}
    ${researchHtml(data.research)}
    <div class="meta">
      <span>Agent <b>${MODE[kind].agent}</b></span>
      <span>${data.latency_ms} ms</span>
      <span>turn ${turnNo}</span>
      ${data.research && data.research.length ? `<span>+${data.research.length} sub-agents</span>` : ""}
    </div>
    <div class="eval-bar">
      <button class="stamp sm run-eval" type="button">Submit to the critic</button>
      <span class="note-inline">LLM-judge generation, linked to this turn</span>
    </div>
    <div class="eval-out"></div>`;

  const output = data.proposal || { reply: data.reply };
  el.querySelector(".run-eval").addEventListener("click", (ev) =>
    runEval(kind, data.generation_id, data.conversation_id, output, ev.currentTarget, el.querySelector(".eval-out"))
  );
}

async function runEval(kind, genId, convId, output, btn, out) {
  btn.disabled = true;
  out.innerHTML = `<div class="developing">The critic is deliberating</div>`;
  try {
    const data = await api("/api/evaluate", {
      method: "POST",
      body: JSON.stringify({
        kind, conversation_id: convId, parent_generation_id: genId,
        context: { latest: threads[kind].history.slice(-2, -1)[0]?.content || "" },
        output,
      }),
    });
    const e = data.result || {};
    const score = Number(e.score) || 0;
    const cls = score >= 8 ? "good" : score >= 5 ? "mid" : "bad";
    const crit = e.criteria || {};
    const bar = (label, v) => {
      const val = Math.max(0, Math.min(10, Number(v) || 0));
      return `<div class="bar-row">
          <span class="bar-label">${label}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${val * 10}%"></span></span>
          <span class="bar-val">${v ?? "–"}</span>
        </div>`;
    };
    out.innerHTML = `
      <div class="critic">
        <div class="score-block">
          <div class="score-num ${cls}">${e.score ?? "?"}</div>
          <div class="score-denom">out of ten</div>
        </div>
        <div class="critic-body">
          <div class="verdict">“${escapeHtml(e.verdict || "")}”</div>
          <p class="reasoning">${escapeHtml(e.reasoning || e.raw || "")}</p>
          <div class="bars">
            ${bar("Relevance", crit.relevance)}
            ${bar("Coherence", crit.coherence)}
            ${bar("Use of catalogue", crit.use_of_catalog)}
          </div>
          <div class="meta" style="margin-top:14px"><span>Agent <b>${kind}-judge</b></span><span>${data.latency_ms} ms</span></div>
        </div>
      </div>`;
  } catch (err) {
    out.innerHTML = `<div class="error" style="text-align:left">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    scrollChat();
  }
}

// --- Boot ------------------------------------------------------------------
async function boot() {
  try {
    const me = await api("/api/me");
    showApp();
    const tb = $("#telemetry-badge");
    const on = me.telemetry.sigil_enabled;
    tb.textContent = on ? "On air" : "Off air";
    tb.className = "onair " + (on ? "on" : "off");
    $("#model-badge").textContent = me.model;
    applyMode();
    await loadCatalog();
  } catch { showLogin(); }
}

boot();
