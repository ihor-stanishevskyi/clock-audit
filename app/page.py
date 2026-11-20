"""The human-facing page.

The API answers machines well and a person badly: opened on a phone, /clocks is
a wall of JSON. This serves one self-contained page at / - no CDN, no fonts, no
build step, because it is served from a Lambda container and must work offline
of everything but itself.

It shows the catalogue honestly: 60 models, of which far fewer are ageing
clocks, and one library that contributes nothing. The page gets those numbers
from the same endpoint as everyone else, so it cannot drift from the service.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ageing-clock coverage audit</title>
<style>
  :root {
    --bg:#fbfaf8; --card:#fff; --text:#1a1a1a; --muted:#666; --line:#e3e0da;
    --accent:#2f6f4f; --ok:#1f7a45; --caution:#9a6a00; --degraded:#a84b10;
    --bad:#a32020; --code:#f1efea;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:#14150f; --card:#1c1e18; --text:#eceade; --muted:#9b9a8e; --line:#30332a;
      --accent:#7fc29b; --ok:#7fc29b; --caution:#d9ad57; --degraded:#e08a4e;
      --bad:#e8736b; --code:#24261e;
    }
  }
  :root[data-theme="dark"] {
    --bg:#14150f; --card:#1c1e18; --text:#eceade; --muted:#9b9a8e; --line:#30332a;
    --accent:#7fc29b; --ok:#7fc29b; --caution:#d9ad57; --degraded:#e08a4e;
    --bad:#e8736b; --code:#24261e;
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.55
    ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  .wrap { max-width:860px; margin:0 auto; padding:28px 16px 72px }
  h1 { font-size:26px; line-height:1.2; margin:0 0 6px; letter-spacing:-.01em }
  .lede { color:var(--muted); margin:0 0 22px; font-size:15px }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:18px; margin:0 0 18px }
  h2 { font-size:15px; text-transform:uppercase; letter-spacing:.08em;
       color:var(--muted); margin:0 0 12px; font-weight:600 }
  p { margin:0 0 12px } p:last-child { margin-bottom:0 }
  code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px }
  code { background:var(--code); padding:1px 5px; border-radius:4px }
  textarea { width:100%; min-height:120px; resize:vertical; padding:11px;
    border:1px solid var(--line); border-radius:8px; background:var(--bg);
    color:var(--text); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px }
  .row { display:flex; flex-wrap:wrap; gap:9px; align-items:center; margin-top:12px }
  button { font:inherit; font-size:14px; padding:9px 15px; border-radius:8px;
    border:1px solid var(--accent); background:var(--accent); color:var(--bg);
    cursor:pointer; font-weight:600 }
  button.ghost { background:transparent; color:var(--text); border-color:var(--line) }
  button:disabled { opacity:.5; cursor:default }
  label.chk { font-size:14px; color:var(--muted); display:flex; align-items:center; gap:6px }
  table { width:100%; border-collapse:collapse; font-size:14px }
  th { text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); font-weight:600; padding:0 8px 7px 0; border-bottom:1px solid var(--line) }
  td { padding:9px 8px 9px 0; border-bottom:1px solid var(--line); vertical-align:top }
  th:last-child, td:last-child { padding-right:0 }
  .num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }
  .pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
          font-weight:700; letter-spacing:.02em; border:1px solid currentColor }
  .ok{color:var(--ok)} .caution{color:var(--caution)} .degraded{color:var(--degraded)}
  .unusable,.refuse{color:var(--bad)}
  .bar { height:5px; border-radius:3px; background:var(--line); margin-top:5px; overflow:hidden }
  .bar > i { display:block; height:100% }
  .tally { display:flex; flex-wrap:wrap; gap:14px; margin:0 0 14px; font-size:14px }
  .muted { color:var(--muted) }
  .warn { border-left:3px solid var(--caution); padding-left:12px; font-size:14px; color:var(--muted) }
  .facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:12px }
  .fact b { display:block; font-size:21px; font-variant-numeric:tabular-nums; line-height:1.2 }
  .fact span { font-size:12.5px; color:var(--muted) }
  footer { color:var(--muted); font-size:13px; margin-top:26px }
  footer a { color:var(--accent) }
  @media (max-width:560px) {
    thead { display:none }
    tbody tr { display:block; padding:11px 0; border-bottom:1px solid var(--line) }
    td { display:flex; justify-content:space-between; gap:12px; border:0; padding:2px 0 }
    td[data-l]::before { content:attr(data-l); color:var(--muted); font-size:12.5px }
    /* Stays a block, or the flex rule above puts the coverage bar beside the
       name and squeezes it to nothing. */
    td.name { display:block; font-weight:600; padding-bottom:8px }
    td.name::before { content:"" }
  }
</style>
<div class="wrap">
  <h1>Ageing-clock coverage audit</h1>
  <p class="lede">An epigenetic clock needs a specific set of CpG sites. If your array
  does not carry them, biolearn fills the gaps from reference medians and returns a
  plausible age anyway &mdash; silently. This tells you first.</p>

  <div class="card">
    <h2>Your sites</h2>
    <textarea id="in" spellcheck="false"
      placeholder="Paste CpG identifiers &mdash; one per line, or comma separated.&#10;cg00000029&#10;cg00000108&#10;cg00000109"></textarea>
    <div class="row">
      <button id="go">Audit</button>
      <button class="ghost" id="demo">Demo: an array carrying only Horvath 2013</button>
      <label class="chk"><input type="checkbox" id="allkinds"> include non-ageing models</label>
    </div>
    <p class="muted" style="margin-top:11px;font-size:13px">
      Identifiers only. Methylation values are never read, never sent, never stored.</p>
  </div>

  <div id="out"></div>

  <div class="card">
    <h2>What is in the catalogue</h2>
    <div class="facts" id="facts"><span class="muted">loading&hellip;</span></div>
    <p class="muted" style="margin-top:14px;font-size:13.5px" id="kindline"></p>
  </div>

  <div class="card">
    <h2>What this cannot tell you</h2>
    <p class="warn" id="caveat">loading&hellip;</p>
  </div>

  <footer>
    API: <a href="/docs">/docs</a> &middot; <a href="/clocks?kind=age">/clocks?kind=age</a>
    &middot; <a href="/health">/health</a><br>
    Coverage is a fact. The verdict is this tool's judgement, and it says so.
  </footer>
</div>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let AGE_NAMES = null;

// Two failures that look alike to fetch() and are nothing alike to a reader:
// the network dropped, or the service answered no. A phone on a flaky
// connection hits the first one often, so retry it once before giving up and
// say which happened - "Failed to fetch" is the browser talking, not us.
async function j(url, opts, retry = true) {
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    if (retry) { await new Promise(s => setTimeout(s, 900)); return j(url, opts, false); }
    throw new Error("No answer from the service. That is usually the connection, "
                    + "not the server - check it and press again.");
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail ? JSON.stringify(body.detail) : "The service refused: HTTP " + r.status);
  return body;
}

// Every number on this page comes from the same endpoints anyone else gets,
// so the page cannot claim more than the service does.
(async () => {
  try {
    const h = await j("/health");
    const k = h.models_by_kind || {};
    $("#facts").innerHTML = [
      [h.age_clock_count, "ageing clocks"],
      [h.model_count, "models in total"],
      [(h.distinct_sites_age_clocks || 0).toLocaleString("en-US"), "distinct CpGs across the ageing clocks"],
      [Object.keys(h.catalogue_from || {}).map(n => n + " " + h.catalogue_from[n]).join(", "), "built from"],
    ].map(([v, l]) => `<div class="fact"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
    if (h.caveat) $("#caveat").textContent = h.caveat;
    const idle = Object.keys(h.installed_but_contributed_nothing || {});
    $("#kindline").innerHTML =
      `Of ${esc(h.model_count)} models: <b>${esc(k.age || 0)}</b> predict age or the rate of ageing, ` +
      `${esc(k.gestational || 0)} read newborns, ${esc(k.mitotic || 0)} count cell divisions, ` +
      `and ${esc(k.other || 0)} predict something else entirely &mdash; smoking, cholesterol, sex, ` +
      `disease status, cell composition. Calling all ${esc(h.model_count)} "ageing clocks" would more ` +
      `than double the real figure.` +
      (idle.length ? ` ${esc(idle.join(", "))} is installed but contributes no model here.` : "");
  } catch (e) {
    $("#facts").textContent = "could not load: " + e.message;
    $("#caveat").textContent = "Could not load the service\u2019s own caveat. "
      + "Treat any number below with more suspicion, not less.";
  }
})();

async function ageNames() {
  if (!AGE_NAMES) AGE_NAMES = (await j("/clocks?kind=age")).clocks.map(c => c.clock);
  return AGE_NAMES;
}

function render(d) {
  const t = d.tally || {};
  const order = ["ok", "caution", "degraded", "unusable", "refuse"];
  const tally = order.filter(k => t[k]).map(k =>
    `<span class="${k}"><b>${t[k]}</b> ${k}</span>`).join("");
  const rows = d.results.map(r => {
    const pct = (r.coverage * 100).toFixed(r.coverage && r.coverage < 0.1 ? 2 : 1) + "%";
    const col = `var(--${r.verdict === "refuse" ? "bad" : r.verdict})`;
    return `<tr>
      <td class="name">${esc(r.clock)}<div class="bar"><i style="width:${Math.max(r.coverage*100,1)}%;background:${col}"></i></div></td>
      <td data-l="verdict"><span class="pill ${esc(r.verdict)}">${esc(r.verdict)}</span></td>
      <td data-l="coverage" class="num">${pct}</td>
      <td data-l="sites" class="num mono">${r.present_sites} / ${r.required_sites}</td>
      <td data-l="signal kept" class="num">${(r.retained_signal*100).toFixed(0)}%</td>
      <td data-l="predicts" class="muted">${esc(r.output || "")}</td>
    </tr>`;
  }).join("");
  const p = d.input.platform_guess;
  $("#out").innerHTML = `<div class="card">
    <h2>Result</h2>
    <div class="tally">${tally}</div>
    <p class="muted" style="font-size:13.5px">
      ${d.input.ids_distinct.toLocaleString("en-US")} distinct identifiers given,
      ${d.input.ids_recognised.toLocaleString("en-US")} recognised by at least one model.
      ${p ? "Looks like " + esc(p) + "." : ""}</p>
    <table><thead><tr><th>Clock</th><th>Verdict</th><th class="num">Coverage</th>
      <th class="num">Sites</th><th class="num">Signal kept</th><th>Predicts</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  if (d.caveat) $("#caveat").textContent = d.caveat;
  $("#out").scrollIntoView({behavior: "smooth", block: "start"});
}

async function run(ids) {
  const btn = $("#go"); btn.disabled = true; btn.textContent = "auditing…";
  try {
    const body = {cpgs: ids};
    if (!$("#allkinds").checked) body.clocks = await ageNames();
    render(await j("/audit", {method: "POST", headers: {"content-type": "application/json"},
                              body: JSON.stringify(body)}));
  } catch (e) {
    $("#out").innerHTML = `<div class="card"><h2>Did not work</h2><p>${esc(e.message)}</p>
      <div class="row"><button id="again">Try again</button></div></div>`;
    $("#again").onclick = () => run(ids);
  } finally { btn.disabled = false; btn.textContent = "Audit"; }
}

$("#go").onclick = () => {
  const ids = $("#in").value.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
  if (!ids.length) { $("#in").focus(); return; }
  run(ids);
};

// The demo is real data, not a mock: an array carrying exactly the 353 sites
// Horvath 2013 asks for. That clock reads perfectly; its neighbours do not -
// which is the whole point, on one screen.
$("#demo").onclick = async () => {
  const b = $("#demo"); b.disabled = true; b.textContent = "loading…";
  try {
    const c = await j("/clocks/Horvathv1");
    $("#in").value = c.sites.join("\n");
    await run(c.sites);
  } catch (e) {
    $("#out").innerHTML = `<div class="card"><h2>Did not work</h2><p>${esc(e.message)}</p>
      <div class="row"><button id="again">Try again</button></div></div>`;
    $("#again").onclick = () => $("#demo").click();
  } finally { b.disabled = false; b.textContent = "Demo: an array carrying only Horvath 2013"; }
};
</script>
</html>
"""
