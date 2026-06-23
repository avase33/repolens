"""Render an Analysis into a self-contained interactive HTML dashboard.

No external assets, no CDN — the report is a single HTML file you can email,
commit, or host anywhere. Charts are drawn with hand-rolled inline SVG/JS so
the file works with zero network access.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .analysis import Analysis


def analysis_to_dict(analysis: Analysis, ai_narrative: str | None = None) -> dict:
    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    data = asdict(analysis)
    data["generated_at"] = iso(analysis.generated_at)
    data["first_commit"] = iso(analysis.first_commit)
    data["last_commit"] = iso(analysis.last_commit)
    data["contributors"] = [
        {**asdict(c), "first": iso(c.first), "last": iso(c.last)}
        for c in analysis.contributors
    ]
    data["ai_narrative"] = ai_narrative
    return data


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RepoLens — __REPO_NAME__</title>
<style>
  :root {
    --bg:#0b0e14; --panel:#141925; --panel2:#1b2230; --ink:#e6edf3;
    --muted:#8b98a9; --line:#26304180; --accent:#5e86ff; --accent2:#7df0c0;
    --warn:#ffb454; --danger:#ff6b6b; --grid:#1f2737;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  a { color:var(--accent); text-decoration:none; }
  .wrap { max-width:1180px; margin:0 auto; padding:32px 24px 80px; }
  header.top { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
  .logo { width:38px;height:38px;border-radius:10px;
    background:linear-gradient(135deg,var(--accent),var(--accent2));
    display:flex;align-items:center;justify-content:center;font-weight:800;color:#0b0e14; }
  h1 { font-size:24px; margin:0; letter-spacing:-.3px; }
  .sub { color:var(--muted); font-size:13px; margin:2px 0 26px; }
  .grid { display:grid; gap:16px; }
  .cards { grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); margin-bottom:26px; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; }
  .card .k { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.6px; }
  .card .v { font-size:28px; font-weight:700; margin-top:6px; letter-spacing:-.5px; }
  .card .v small { font-size:13px; color:var(--muted); font-weight:500; }
  section { background:var(--panel); border:1px solid var(--line); border-radius:16px;
    padding:22px 24px; margin-bottom:20px; }
  section h2 { font-size:16px; margin:0 0 4px; }
  section .desc { color:var(--muted); font-size:13px; margin:0 0 18px; max-width:70ch; }
  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.4px; }
  td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
  tr:hover td { background:var(--panel2); }
  .path { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; }
  .bar { height:7px; border-radius:4px; background:var(--grid); position:relative; overflow:hidden; min-width:60px; }
  .bar > span { position:absolute; inset:0 auto 0 0; border-radius:4px; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11.5px; font-weight:600; }
  .pill.hi { background:#ff6b6b22; color:var(--danger); }
  .pill.mid { background:#ffb45422; color:var(--warn); }
  .pill.ok { background:#7df0c022; color:var(--accent2); }
  .ai { background:linear-gradient(180deg,#16203a,#141925); border:1px solid #2a3a63; }
  .ai .badge { font-size:11px; color:var(--accent); border:1px solid #2a3a63; border-radius:999px; padding:2px 9px; }
  .ai p { white-space:pre-wrap; margin:12px 0 0; }
  .muted { color:var(--muted); }
  svg text { fill:var(--muted); font-size:11px; }
  .legend { display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; font-size:12px; color:var(--muted); }
  .dot { display:inline-block; width:9px;height:9px;border-radius:50%; margin-right:5px; vertical-align:middle;}
  footer { color:var(--muted); font-size:12px; text-align:center; margin-top:30px; }
  .empty { color:var(--muted); font-style:italic; padding:8px 0; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="logo">R</div>
    <div>
      <h1>RepoLens · __REPO_NAME__</h1>
    </div>
  </header>
  <p class="sub" id="sub"></p>

  <div class="grid cards" id="cards"></div>

  <section class="ai" id="ai-section" style="display:none">
    <span class="badge">AI BRIEFING</span>
    <p id="ai-text"></p>
  </section>

  <section>
    <h2>Activity over time</h2>
    <p class="desc">Commits per month across the project's life. Spikes and lulls
      often map to releases, rewrites, or team changes.</p>
    <div id="timeline"></div>
  </section>

  <section>
    <h2>🔥 Hotspots</h2>
    <p class="desc">Files where high change-frequency meets high complexity — the
      geometric mean of how often a file changes and how large it is. These are
      the most likely places for bugs to hide and the highest-value refactor
      targets.</p>
    <table id="hotspots"></table>
  </section>

  <section>
    <h2>🔗 Temporal coupling</h2>
    <p class="desc">Pairs of files that keep changing together in the same commit.
      Strong coupling between files in different modules can reveal hidden
      dependencies that the architecture doesn't make obvious.</p>
    <table id="coupling"></table>
  </section>

  <section>
    <h2>🧠 Knowledge risk</h2>
    <p class="desc">"Knowledge islands" are actively-changing files understood by
      exactly one person. If that person leaves, the knowledge leaves with them.
      Bus factor estimates how many people hold the majority of the codebase.</p>
    <table id="islands"></table>
  </section>

  <section>
    <h2>👥 Contributors</h2>
    <p class="desc">Who has shaped this codebase, by commits and lines changed.</p>
    <table id="contributors"></table>
  </section>

  <footer>Generated by <strong>RepoLens</strong> v__VERSION__ · runs fully offline · __GENERATED__</footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const esc = s => String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = n => (n==null?'—':Number(n).toLocaleString());
const shortDate = s => s ? s.slice(0,10) : '—';

function lifespan() {
  if (!D.first_commit || !D.last_commit) return '—';
  const days = Math.max(1, Math.round((new Date(D.last_commit)-new Date(D.first_commit))/86400000));
  if (days < 90) return days + ' days';
  if (days < 730) return Math.round(days/30) + ' months';
  return (days/365).toFixed(1) + ' years';
}

// --- summary cards ---
document.getElementById('sub').textContent =
  `${shortDate(D.first_commit)} → ${shortDate(D.last_commit)} · analysed ${fmt(D.total_commits)} commits`;

const busClass = D.bus_factor <= 1 ? 'hi' : (D.bus_factor <= 2 ? 'mid':'ok');
const cards = [
  ['Commits', fmt(D.total_commits), ''],
  ['Files tracked', fmt(D.total_files), ''],
  ['Contributors', fmt(D.contributors.length), ''],
  ['Project age', lifespan(), ''],
  ['Bus factor', `<span class="pill ${busClass}">${D.bus_factor}</span>`, 'people hold the majority'],
  ['Knowledge islands', fmt(D.knowledge_islands.length), 'single-owner hot files'],
];
document.getElementById('cards').innerHTML = cards.map(([k,v,s]) =>
  `<div class="card"><div class="k">${k}</div><div class="v">${v} ${s?`<small>${s}</small>`:''}</div></div>`).join('');

// --- AI narrative ---
if (D.ai_narrative) {
  document.getElementById('ai-section').style.display = '';
  document.getElementById('ai-text').textContent = D.ai_narrative;
}

// --- timeline (inline SVG bar chart) ---
(function(){
  const data = D.monthly_activity;
  const el = document.getElementById('timeline');
  if (!data.length){ el.innerHTML='<div class="empty">No activity data.</div>'; return; }
  const W=1100, H=180, pad=30;
  const max = Math.max(...data.map(d=>d[1]));
  const bw = (W-pad*2)/data.length;
  let bars='', labels='';
  data.forEach((d,i)=>{
    const h=(d[1]/max)*(H-pad*2);
    const x=pad+i*bw, y=H-pad-h;
    bars+=`<rect x="${x+1}" y="${y}" width="${Math.max(1,bw-2)}" height="${h}" rx="2" fill="var(--accent)"><title>${d[0]}: ${d[1]} commits</title></rect>`;
    if (i % Math.ceil(data.length/12)===0)
      labels+=`<text x="${x}" y="${H-10}">${d[0]}</text>`;
  });
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">
    <text x="${pad}" y="16">peak ${max} commits/mo</text>${bars}${labels}</svg>`;
})();

// --- bar cell helper ---
function barCell(val, max, color){
  const pct = max? Math.round((val/max)*100):0;
  return `<div class="bar"><span style="width:${pct}%;background:${color}"></span></div>`;
}

// --- hotspots ---
(function(){
  const rows = D.hotspots;
  const el = document.getElementById('hotspots');
  if (!rows.length){ el.innerHTML='<tr><td class="empty">No hotspots found.</td></tr>'; return; }
  const maxScore = Math.max(...rows.map(r=>r.score));
  el.innerHTML = `<thead><tr><th>File</th><th class="num">Changes</th><th class="num">Lines</th>
    <th>Hotspot score</th><th>Owner</th></tr></thead><tbody>` +
    rows.map(r=>{
      const own = r.ownership>=0.8?'hi':(r.ownership>=0.5?'mid':'ok');
      return `<tr><td class="path">${esc(r.path)}</td>
      <td class="num">${fmt(r.revisions)}</td>
      <td class="num">${r.loc?fmt(r.loc):'<span class="muted">—</span>'}</td>
      <td>${barCell(r.score,maxScore,'var(--danger)')}</td>
      <td><span class="muted">${esc(r.main_author||'—')}</span> <span class="pill ${own}">${Math.round(r.ownership*100)}%</span></td></tr>`;
    }).join('') + '</tbody>';
})();

// --- coupling ---
(function(){
  const rows = D.couplings;
  const el = document.getElementById('coupling');
  if (!rows.length){ el.innerHTML='<tr><td class="empty">No significant coupling detected.</td></tr>'; return; }
  el.innerHTML = `<thead><tr><th>File A</th><th>File B</th><th class="num">Shared commits</th><th>Coupling</th></tr></thead><tbody>`+
    rows.map(r=>{
      const deg=Math.round(r.degree*100);
      const cls=deg>=70?'hi':(deg>=50?'mid':'ok');
      return `<tr><td class="path">${esc(r.file_a)}</td><td class="path">${esc(r.file_b)}</td>
      <td class="num">${fmt(r.shared)}</td>
      <td><span class="pill ${cls}">${deg}%</span></td></tr>`;
    }).join('')+'</tbody>';
})();

// --- knowledge islands ---
(function(){
  const rows = D.knowledge_islands;
  const el = document.getElementById('islands');
  if (!rows.length){ el.innerHTML='<tr><td class="empty">No single-owner hot files — knowledge looks well distributed. 🎉</td></tr>'; return; }
  el.innerHTML = `<thead><tr><th>File</th><th>Sole owner</th><th class="num">Changes</th><th class="num">Lines</th></tr></thead><tbody>`+
    rows.map(r=>`<tr><td class="path">${esc(r.path)}</td>
      <td><span class="pill hi">${esc(r.main_author||'—')}</span></td>
      <td class="num">${fmt(r.revisions)}</td>
      <td class="num">${r.loc?fmt(r.loc):'—'}</td></tr>`).join('')+'</tbody>';
})();

// --- contributors ---
(function(){
  const rows = D.contributors.slice(0,20);
  const el = document.getElementById('contributors');
  if (!rows.length){ el.innerHTML='<tr><td class="empty">No contributors.</td></tr>'; return; }
  const maxC = Math.max(...rows.map(r=>r.commits));
  el.innerHTML = `<thead><tr><th>Contributor</th><th class="num">Commits</th><th>Share</th>
    <th class="num">+ added</th><th class="num">− removed</th><th>Active</th></tr></thead><tbody>`+
    rows.map(r=>`<tr><td>${esc(r.name)}</td>
      <td class="num">${fmt(r.commits)}</td>
      <td>${barCell(r.commits,maxC,'var(--accent2)')}</td>
      <td class="num" style="color:var(--accent2)">${fmt(r.insertions)}</td>
      <td class="num" style="color:var(--danger)">${fmt(r.deletions)}</td>
      <td class="muted">${shortDate(r.first)} → ${shortDate(r.last)}</td></tr>`).join('')+'</tbody>';
})();
</script>
</body>
</html>
"""


def render_html(analysis: Analysis, ai_narrative: str | None = None, version: str = "0.1.0") -> str:
    data = analysis_to_dict(analysis, ai_narrative)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = _TEMPLATE
    html = html.replace("__REPO_NAME__", _escape(analysis.repo_name))
    html = html.replace("__VERSION__", version)
    html = html.replace(
        "__GENERATED__", analysis.generated_at.strftime("%Y-%m-%d %H:%M")
    )
    html = html.replace("__DATA__", payload)
    return html


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def write_report(
    analysis: Analysis, out_path: str | Path, ai_narrative: str | None = None, version: str = "0.1.0"
) -> Path:
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(analysis, ai_narrative, version), encoding="utf-8")
    return out
