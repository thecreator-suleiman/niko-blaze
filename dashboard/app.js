const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}},
               set(k,v){try{localStorage.setItem(k,v)}catch(e){}}, del(k){try{localStorage.removeItem(k)}catch(e){}}};
let DATA = null;

function table(el, rows, cols) {
  el.innerHTML = "<tr>" + cols.map(c => `<th>${c[0]}</th>`).join("") + "</tr>" +
    (rows.length ? rows.map(r => "<tr>" + cols.map(c => `<td>${c[1](r)}</td>`).join("") + "</tr>").join("")
                 : `<tr><td colspan="${cols.length}" class="muted">nothing yet</td></tr>`);
}
const st = s => `<span class="s-${esc(s)}">${esc(s)}</span>`;
const fmt = t => t ? new Date(t).toLocaleString() : "";

function render(d) {
  DATA = d;
  $("#state").textContent = d.paused ? "PAUSED" : "RUNNING";
  $("#state").className = "pill " + (d.paused ? "pause" : "run");
  const c = d.credits, q = d.quality;
  const k = [["Songs accepted", q.accepted], ["Songs rejected by QC", q.rejected], ["Avg quality score", q.average_score],
             ["GPU hours left (week)", c.kaggle_gpu_hours_left], ["Uploads today", c.youtube_uploads_today],
             ["YouTube", d.config.youtube_enabled ? d.config.privacy : "off"]];
  $("#kpis").innerHTML = k.map(([a,b]) => `<div class="k"><b>${esc(b)}</b><span>${esc(a)}</span></div>`).join("");
  const labels = {reggae:"Reggae", afrobeats:"Afrobeats / Amapiano", relaxation:"Relaxation"};
  $("#depts").innerHTML = Object.entries(d.departments).map(([n,v]) => `<div class="d ${n}"><h3>${labels[n]}</h3>
    <div class="muted">Library: <b>${v.library_tracks}</b> tracks · ${v.library_minutes} min · new today: ${v.today_new}</div>
    <div class="muted">Last mix: ${v.last_mix ? esc(v.last_mix.title || v.last_mix.id) + " — " + st(v.last_mix.status) : "none yet"}</div></div>`).join("");
  $("#credits").innerHTML = [
    ["Kaggle GPU used (7 days)", c.kaggle_gpu_hours_used_7d + " h / " + c.kaggle_weekly_limit + " h"],
    ["YouTube uploads today", c.youtube_uploads_today], ["YouTube API units today", c.youtube_units_today],
    ["GitHub Models calls today", c.llm_calls_today.github_models], ["Gemini calls today", c.llm_calls_today.gemini],
    ["Lyrics providers available", (d.config.llm_available || []).join(", ") || "none"],
    ["Music provider", d.config.provider]].map(([a,b]) => `<div><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join("");
  $("#thumbs").innerHTML = d.uploads.filter(u => u.thumb).slice(0, 24).map(u =>
    `<figure><a href="${u.youtube_id ? "https://youtu.be/" + esc(u.youtube_id) : esc(u.thumb)}" target="_blank" rel="noopener">
     <img loading="lazy" src="${esc(u.thumb)}" alt=""></a><figcaption>${esc(u.title || u.ref_id)}</figcaption></figure>`).join("")
    || '<span class="muted">No thumbnails yet</span>';
  table($("#uploads"), d.uploads, [["Item", u => esc(u.title || u.ref_id)], ["Kind", u => esc(u.kind)], ["Status", u => st(u.status)],
    ["Privacy", u => esc(u.privacy)], ["Video", u => u.youtube_id ? `<a href="https://youtu.be/${esc(u.youtube_id)}" target="_blank">${esc(u.youtube_id)}</a>` : ""],
    ["Publish at", u => fmt(u.publish_at)], ["Error", u => esc((u.error || "").slice(0, 80))]]);
  table($("#songs"), d.songs, [["Title", s => esc(s.title)], ["Dept", s => esc(s.department)], ["Style", s => esc(s.subgenre)],
    ["Status", s => st(s.status)], ["QC", s => s.qc_score ?? ""], ["Tries", s => s.attempts],
    ["Length", s => s.master_duration ? (s.master_duration/60).toFixed(1) + " min" : ""], ["Created", s => fmt(s.created_at)],
    ["Note", s => esc((s.error || "").slice(0, 70))]]);
  table($("#lic"), Object.entries(d.licensing.components), [["Component", e => esc(e[0])], ["Status", e => st(e[1].status)],
    ["Licence", e => esc(e[1].licence)], ["Commercial use", e => esc(e[1].commercial)]]);
  drawEvents();
  $("#foot").textContent = `Snapshot ${fmt(d.generated_at)} · portrait file ${d.licensing.portrait_file_present ? "present" : "missing (silhouette used)"}`;
}

function drawEvents() {
  const only = $("#onlyerr").checked;
  $("#events").innerHTML = (DATA?.events || []).filter(e => !only || e.level !== "info").map(e =>
    `<div class="l-${esc(e.level)}">${esc(e.ts)} [${esc(e.stage)}] ${esc(e.message)}</div>`).join("") || "no events";
}
$("#onlyerr").onchange = drawEvents;

async function dispatch(action) {
  const repo = DATA?.repo, msg = $("#ctlmsg"), tok = store.get("nb_tok");
  if (!repo) { msg.textContent = "Repository unknown (dashboard data not generated yet)."; return; }
  const dept = $("#dept").value;
  if (!tok) { window.open(`https://github.com/${repo}/actions/workflows/control.yml`, "_blank"); return; }
  msg.textContent = "Sending…";
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/control.yml/dispatches`, {
      method: "POST", headers: {Authorization: `Bearer ${tok}`, Accept: "application/vnd.github+json"},
      body: JSON.stringify({ref: "main", inputs: {action, department: dept}})});
    msg.textContent = r.status === 204 ? `“${action}” started — the dashboard refreshes when it finishes.` : `GitHub replied ${r.status}`;
  } catch (e) { msg.textContent = "Network error: " + e; }
}
document.querySelectorAll("[data-a]").forEach(b => b.onclick = () => dispatch(b.dataset.a));
$("#savetok").onclick = () => { store.set("nb_tok", $("#tok").value.trim()); $("#tok").value = ""; $("#ctlmsg").textContent = "Token saved on this device."; };
$("#cleartok").onclick = () => { store.del("nb_tok"); $("#ctlmsg").textContent = "Token removed."; };

fetch("data/status.json", {cache: "no-store"}).then(r => r.json()).then(render)
  .catch(() => { $("#state").textContent = "NO DATA YET"; });
