from __future__ import annotations

import json
from pathlib import Path


def publish_agent_d(output_dir: str) -> str:
    out = Path(output_dir)
    view_path = out / "judge_view.json"
    if not view_path.is_file():
        raise FileNotFoundError(f"missing judge_view.json: {view_path}")
    data = json.loads(view_path.read_text(encoding="utf-8"))
    html_path = out / "index.html"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html_path.write_text(_html(payload), encoding="utf-8")
    return str(html_path)


def _html(payload: str) -> str:
    return _TEMPLATE.replace("__CSS__", _CSS).replace("__REST__", _JS).replace("__PAYLOAD__", payload)


_CSS = """
:root {
  --bg:#eef1ee; --panel:#ffffff; --ink:#1b1f1c; --muted:#5e6a63;
  --line:#d3dad1; --soft:#eef3ec; --accent:#0f6b58; --accent2:#8a5418;
  --ok:#1f8a63; --partial:#c8860d; --bad:#c0392b; --unknown:#8a928c;
  --ok-soft:#e3f4ec; --partial-soft:#fcf1d8; --bad-soft:#fbe4e0; --unknown-soft:#eceeec;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; }
header { border-bottom:1px solid var(--line); background:#fff; padding:12px 26px; position:sticky; top:0; z-index:5; }
.banner { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.banner .crumbs { font-size:12px; color:var(--muted); }
.banner h1 { margin:0; font-size:19px; letter-spacing:0; }
.banner .team { font-size:15px; font-weight:650; color:var(--accent); }
.banner .tag-base { background:var(--accent2); color:#fff; border-radius:5px; padding:3px 9px; font-size:12px; font-weight:600; }
.banner .tag-school { background:var(--soft); border:1px solid var(--line); color:#33453d; border-radius:5px; padding:3px 9px; font-size:12px; }
.banner .repo-link { font-size:12px; color:var(--muted); margin-left:auto; }
.banner .repo-link a { color:var(--accent); text-decoration:none; }
main { display:grid; grid-template-columns:minmax(280px,360px) 1fr; min-height:calc(100vh - 56px); }
aside { border-right:1px solid var(--line); padding:14px 12px; overflow:auto; max-height:calc(100vh - 56px); background:#fff; }
section { padding:22px 28px 70px; overflow:auto; max-height:calc(100vh - 56px); }
.tree ul { list-style:none; margin:0; padding-left:13px; border-left:1px solid var(--line); }
.tree > ul { padding-left:0; border-left:0; }
.tree li { margin:3px 0; }
button.node { width:100%; border:0; background:transparent; text-align:left; padding:6px 8px; border-radius:6px; color:var(--ink); cursor:pointer; display:flex; gap:8px; align-items:center; font:inherit; border-left:3px solid transparent; }
button.node:hover { background:#e6ede7; }
button.node.active { background:#dfeae2; border-left-color:var(--accent); }
.dot { width:8px; height:8px; border-radius:99px; flex:0 0 auto; background:var(--unknown); }
.implemented .dot { background:var(--ok); } .partial .dot { background:var(--partial); } .not_found .dot { background:var(--bad); }
.label { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.node-title { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; border-bottom:2px solid var(--accent); padding-bottom:12px; margin-bottom:4px; }
.node-title h2 { margin:0; font-size:24px; }
.node-title .en { color:var(--muted); font-size:14px; margin-top:2px; }
.node-title .path { color:var(--muted); font-size:12px; margin-top:4px; font-family:ui-monospace,Consolas,monospace; }
.node-title .concept { margin-top:8px; max-width:60ch; line-height:1.5; color:#36433d; }
.badge { display:inline-flex; align-items:center; min-height:22px; padding:2px 9px; border-radius:999px; font-size:12px; background:var(--soft); color:#274b42; margin:0 5px 5px 0; }
.badge.ok { background:var(--ok-soft); color:#0f6b46; } .badge.partial { background:var(--partial-soft); color:#7a560a; }
.badge.bad { background:var(--bad-soft); color:#9a2b1f; } .badge.unknown { background:var(--unknown-soft); color:#5b635d; }
.badge.mat-textbook { background:#e6eef7; color:#2d5288; } .badge.mat-simplified { background:#fcf1d8; color:#7a560a; } .badge.mat-production { background:#e3f4ec; color:#0f6b46; }
.grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:15px; margin-top:16px; align-items:start; }
.wide { grid-column:1 / -1; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:9px; padding:15px; border-left:4px solid var(--line); }
.panel.accent { border-left-color:var(--accent); }
.panel h3 { margin:0 0 10px; font-size:14px; color:#2a3a33; }
.panel p { color:#41504a; line-height:1.55; margin:6px 0; }
.list { margin:0; padding-left:18px; color:#374740; line-height:1.6; }
.empty { color:var(--muted); font-style:italic; }
.muted { color:var(--muted); }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:13px; margin-top:18px; }
button.card { text-align:left; border:1px solid var(--line); border-left:4px solid var(--unknown); border-radius:9px; padding:13px; background:#fff; cursor:pointer; font:inherit; display:block; width:100%; }
button.card:hover { box-shadow:0 1px 8px rgba(0,0,0,.08); }
button.card.implemented { border-left-color:var(--ok); } button.card.partial { border-left-color:var(--partial); } button.card.not_found { border-left-color:var(--bad); }
button.card h4 { margin:0 0 4px; font-size:15px; }
button.card .cpath { font-size:11px; color:var(--muted); font-family:ui-monospace,Consolas,monospace; }
button.card p { font-size:13px; color:#46544d; margin:7px 0 9px; line-height:1.5; max-height:4.6em; overflow:hidden; }
.claim-item { border:1px solid var(--line); border-left:4px solid var(--unknown); border-radius:8px; padding:12px 14px; margin:11px 0; background:#fff; }
.claim-item.implemented { border-left-color:var(--ok); } .claim-item.partial { border-left-color:var(--partial); } .claim-item.not_found { border-left-color:var(--bad); }
.claim-head { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }
.claim-name { font-weight:650; font-size:15px; color:#16453a; }
.claim-raw { color:var(--muted); font-size:11px; font-family:ui-monospace,Consolas,monospace; margin-top:2px; }
.claim-def { margin:8px 0; color:#3c4a44; line-height:1.55; }
.claim-statement { margin:6px 0; line-height:1.55; }
.ev-pills { display:flex; gap:6px; flex-wrap:wrap; margin-top:9px; }
.ev-pill { border:1px solid var(--line); background:var(--soft); border-radius:999px; padding:3px 9px; font-family:ui-monospace,Consolas,monospace; font-size:11px; color:#1f4a43; cursor:pointer; }
.ev-pill:hover { background:#d8e6dd; }
details.ev { margin:6px 0; border:1px solid var(--line); border-radius:6px; background:#fbfcfb; overflow:hidden; }
details.ev summary { cursor:pointer; padding:8px 10px; color:#1f4a43; font-size:12.5px; font-family:ui-monospace,Consolas,monospace; overflow-wrap:anywhere; }
details.ev[open] { border-color:var(--accent); }
pre { margin:0; padding:12px; overflow:auto; max-height:300px; background:#1d2422; color:#eaf3ec; font-size:12px; line-height:1.45; }
code { font-family:ui-monospace,Consolas,monospace; font-size:12px; background:#e9efe9; padding:2px 5px; border-radius:4px; overflow-wrap:anywhere; }
.glossary-detail { margin:9px 0 0; border:0; background:#f1f5f0; border-radius:6px; }
.glossary-detail summary { color:#33473f; padding:7px 10px; cursor:pointer; font-size:12.5px; }
.example-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px; }
.example-grid pre { max-height:170px; border-radius:5px; }
.symbol-table { width:100%; border-collapse:collapse; table-layout:fixed; }
.symbol-table th { text-align:left; color:var(--muted); font-size:12px; border-bottom:1px solid var(--line); padding:6px; }
.symbol-table td { border-bottom:1px solid #edf0ec; padding:7px 6px; vertical-align:top; overflow-wrap:anywhere; }
.kind { color:var(--accent); font-size:12px; white-space:nowrap; }
.path { color:var(--muted); font-size:12px; font-family:ui-monospace,Consolas,monospace; }
.flow-lane { display:flex; align-items:center; flex-wrap:wrap; gap:0; margin:8px 0; }
.flow-step { background:var(--soft); border:1px solid var(--line); border-radius:6px; padding:5px 10px; font-size:12.5px; color:#274b42; }
.flow-arrow { color:var(--accent); margin:0 6px; font-weight:700; }
.flow-title { font-weight:600; margin:14px 0 2px; color:#2a3a33; }
.dep-graph { width:100%; height:auto; background:#fbfcfb; border:1px solid var(--line); border-radius:8px; }
.dep-graph text { font-size:11px; fill:#2a3a33; font-family:Inter,sans-serif; }
.dep-row { border-top:1px solid #edf0ec; padding:8px 0; }
.dep-row:first-child { border-top:0; }
.legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin:8px 0; }
.legend span { display:inline-flex; align-items:center; gap:5px; }
.legend i { width:10px; height:10px; border-radius:3px; display:inline-block; }
@media (max-width:900px){ main{grid-template-columns:1fr;} aside{max-height:40vh;border-right:0;border-bottom:1px solid var(--line);} section{max-height:none;} .grid{grid-template-columns:1fr;} }
"""


_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>内核设计抽象树</title>
<style>__CSS__</style>
</head>
<body>
<header><div class="banner" id="banner"></div></header>
<main>
  <aside><div class="tree" id="tree"></div></aside>
  <section id="detail"></section>
</main>
<script type="application/json" id="agent-d-data">__PAYLOAD__</script>
<script>
__REST__
</script>
</body>
</html>"""


_JS = r"""
const DATA = JSON.parse(document.getElementById('agent-d-data').textContent);
const byNode = new Map();
(function flatten(n){ byNode.set(n.node_id, n); (n.children||[]).forEach(flatten); })(DATA.tree);

function escapeHtml(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function cleanPath(p){ return String(p||'').replace(/\\/g,'/'); }
function escapeControlChars(s){ return Array.from(String(s||'')).map(ch=>{ const c=ch.charCodeAt(0); if(ch==='\n'||ch==='\r'||ch==='\t'||c>=32) return ch; return '\\x'+c.toString(16).padStart(2,'0'); }).join(''); }
function statusOf(n){ if(n.status) return n.status; const k=n.children||[]; if(k.some(x=>statusOf(x)==='implemented')) return 'implemented'; if(k.some(x=>statusOf(x)==='partial')) return 'partial'; if(k.length&&k.every(x=>statusOf(x)==='not_found')) return 'not_found'; return 'unknown'; }
function badge(t,cls){ return t?`<span class="badge ${cls||''}">${escapeHtml(t)}</span>`:''; }
function list(xs){ return xs&&xs.length?`<ul class="list">${xs.map(x=>`<li>${escapeHtml(String(x))}</li>`).join('')}</ul>`:`<div class="empty">无</div>`; }
const ACR={sv39:'Sv39',pte:'PTE',satp:'satp',vma:'VMA',fat32:'FAT32',ext4:'ext4',sbi:'SBI',uart:'UART',virtio:'VirtIO',qemu:'QEMU',ipc:'IPC',rcu:'RCU',tlb:'TLB',dma:'DMA',plic:'PLIC',vfs:'VFS',elf:'ELF',mmap:'mmap',smp:'SMP',vdso:'VDSO',kaslr:'KASLR'};
function formatTag(t){ return String(t||'').replace(/^(extension|data|policy|interface):/,'').split('_').map(w=>ACR[w.toLowerCase()]||w).join(' '); }
function formatNodeId(id){ return String(id||'').split('.').join(' / '); }
// Skip the legacy templated concept ("X / Y: source-backed design responsibilities inside Z").
function realConcept(s){ const t=String(s||'').trim(); if(!t||/source-backed design responsibilities inside/.test(t)) return ''; return t; }
// Avoid printing the English title twice when zh and en are identical.
function bilingual(zh,en){ const a=escapeHtml(zh||''); const b=escapeHtml(en||''); return (b&&b!==a)?`${a} <span class="muted">/ ${b}</span>`:a; }
const MAT={textbook:'教学级',simplified:'精简实现',production:'生产级'};
function matBadge(m){ return m&&MAT[m]?`<span class="badge mat-${m}">${MAT[m]}</span>`:''; }

// ---- banner (参赛信息) ----
(function renderBanner(){
  const sm = DATA.submission_meta || {};
  const repo = escapeHtml(DATA.repo_name || sm.repo_name || 'kernel');
  let mid = `<span class="crumbs">内核设计抽象树</span><h1>${repo}</h1>`;
  if (sm.is_base_os) {
    mid += `<span class="tag-base">${escapeHtml(sm.label_zh || '教学原型 OS')}</span>`;
  } else if (sm.team || sm.school) {
    if (sm.year || sm.contest || sm.track) mid += `<span class="crumbs">${[sm.year,sm.contest,sm.track].filter(Boolean).map(escapeHtml).join(' · ')}</span>`;
    if (sm.team) mid += `<span class="team">${escapeHtml(sm.team)}</span>`;
    if (sm.school) mid += `<span class="tag-school">${escapeHtml(sm.school)}</span>`;
  }
  if (sm.repo_url) mid += `<span class="repo-link"><a href="${escapeHtml(sm.repo_url)}" target="_blank" rel="noopener">${escapeHtml(sm.repo_url)}</a></span>`;
  document.getElementById('banner').innerHTML = mid;
})();

// ---- left tree ----
function renderTree(node){
  const has = node.children && node.children.length;
  const title = `${node.title_zh || node.node_id}`;
  return `<li><button class="node ${statusOf(node)}" data-id="${escapeHtml(node.node_id)}"><span class="dot"></span><span class="label">${escapeHtml(title)}</span></button>${has?`<ul>${node.children.map(renderTree).join('')}</ul>`:''}</li>`;
}
document.getElementById('tree').innerHTML = `<ul>${renderTree(DATA.tree)}</ul>`;
document.getElementById('tree').addEventListener('click', e=>{
  const btn = e.target.closest('button.node'); if(!btn) return;
  document.querySelectorAll('button.node').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderDetail(byNode.get(btn.dataset.id));
});
document.getElementById('detail').addEventListener('click', e=>{
  const pill = e.target.closest('.ev-pill'); if(pill){ const t=document.getElementById(pill.dataset.target); if(t){ t.open=true; t.scrollIntoView({behavior:'smooth',block:'center'}); } return; }
  const card = e.target.closest('button.card'); if(card){ const n=byNode.get(card.dataset.id); if(n){ document.querySelectorAll('button.node').forEach(b=>b.classList.toggle('active', b.dataset.id===n.node_id)); renderDetail(n); window.scrollTo({top:0}); } }
});

// ---- evidence + claims ----
function evidenceBlock(eid, anchor){
  const e = DATA.evidence[eid] || {};
  const loc = [cleanPath(e.path), e.line_start?(':'+e.line_start):''].join('');
  const sym = escapeControlChars(e.symbol || e.label || '');
  const label = `${eid}  ${loc}  ${sym}  ${e.kind||''}  ${e.strength||''}`;
  return `<details class="ev" id="${escapeHtml(anchor||('ev-'+eid))}"><summary>${escapeHtml(label)}</summary><pre>${escapeHtml(escapeControlChars(e.excerpt||'no excerpt'))}</pre></details>`;
}
function glossaryDetail(g){
  if(!g || g.status!=='ok') return '';
  const cues = (g.recognition_cues||[]).map(x=>`<span class="badge">${escapeHtml(x)}</span>`).join('');
  const conf = (g.confusions&&g.confusions.length)?list(g.confusions):'';
  const ex = (g.c_example||g.rust_example)?`<div class="example-grid"><div><b>C 识别样例</b><pre>${escapeHtml(g.c_example||'—')}</pre></div><div><b>Rust 识别样例</b><pre>${escapeHtml(g.rust_example||'—')}</pre></div></div>`:'';
  if(!cues && !conf && !ex) return '';
  return `<details class="glossary-detail"><summary>概念辨析与识别样例</summary><div style="padding:0 10px 10px">${cues?`<p><b>识别线索：</b>${cues}</p>`:''}${conf?`<p><b>常见混淆：</b></p>${conf}`:''}${ex}<p class="muted">词典释义与样例仅帮助理解，不作为源码证据。</p></div></details>`;
}
// One claim, WITHOUT its evidence body (evidence is collected separately below).
function claimItem(cid){
  const c = DATA.claims[cid]; if(!c) return '';
  const g = c.glossary || {};
  const tzh = g.title_zh || formatTag(c.canonical_tag);
  const ten = g.title_en || '';
  const def = (g.status==='ok') ? (g.definition_zh||'') : '';
  return `<div class="claim-item ${c.status||'unknown'}"><div class="claim-head"><div><div class="claim-name">${bilingual(tzh,ten)}</div><div class="claim-raw">${escapeHtml(c.canonical_tag)}</div></div><div>${badge(c.status, c.status==='not_found'?'bad':c.status==='partial'?'partial':c.status==='implemented'?'ok':'unknown')}${matBadge(c.maturity)}</div></div>${def?`<p class="claim-def">${escapeHtml(def)}</p>`:''}<p class="claim-statement">${escapeHtml(c.statement_zh||'')}</p>${(c.statement_en&&c.statement_en!==c.statement_zh)?`<p class="claim-statement muted">${escapeHtml(c.statement_en)}</p>`:''}${glossaryDetail(g)}<div class="ev-pills">${(c.evidence_ids||[]).map(id=>`<button class="ev-pill" data-target="ev-${escapeHtml(id)}">${escapeHtml(id)}</button>`).join('')}</div></div>`;
}

// ---- key symbols table ----
function cleanSym(s){ let x=escapeControlChars(s).trim().replace(/\\+$/,'').replace(/^\/\/\s*/,''); if(x.length>52) x=x.slice(0,49)+'...'; return x||'unnamed'; }
function symRank(s){ const k=String(s.kind||''); return k==='function'?1:(k==='type'||k==='type_definition')?2:k==='assembly_label'?3:(k==='macro_definition'||k==='constant_definition')?4:(k==='config_entry'||k==='linker_symbol')?5:9; }
function symbolTable(xs){
  const rows=(xs||[]).filter(s=>s&&s.name&&!String(s.name).trim().startsWith('//')).map(s=>({...s,name:cleanSym(s.name),path:cleanPath(s.path),rank:symRank(s)})).filter(s=>s.name.length<=64).sort((a,b)=>a.rank-b.rank||String(a.path).localeCompare(String(b.path))).slice(0,10);
  if(!rows.length) return '<div class="empty">无</div>';
  return `<table class="symbol-table"><thead><tr><th style="width:36%">符号/配置</th><th style="width:16%">类型</th><th>定位</th></tr></thead><tbody>${rows.map(s=>`<tr><td><code>${escapeHtml(s.name)}</code></td><td class="kind">${escapeHtml(s.kind||'')}</td><td class="path">${escapeHtml(s.path)}:${escapeHtml(s.line||'')}</td></tr>`).join('')}</tbody></table>`;
}

// ---- flows as horizontal lanes ----
const DEP_ZH={ allocates_page_table_pages:'页表创建需要物理页分配', copies_user_buffers:'系统调用需要安全拷贝用户缓冲区', dispatches_file_syscalls:'文件类系统调用进入文件描述符层', owns_page_tables:'地址空间拥有并管理页表', protects_process_table:'调度器依赖锁保护进程状态', file_objects_bound_to_fd:'fd 表绑定内核 file 对象', persists_blocks:'inode 数据最终落到块设备', uses_buffered_block_io:'文件系统通过缓存块 I/O 访问设备', entered_from_trap:'设备中断从 trap/interrupt 入口进入' };
function depText(d){ return DEP_ZH[d.relation] || d.reason_zh || d.relation || ''; }
function flowLane(f){
  const steps=(f.role_sequence&&f.role_sequence.length?f.role_sequence:(f.steps||[]).map(s=>s.role)).filter(Boolean);
  const lane=steps.map((s,i)=>`<span class="flow-step">${escapeHtml(formatTag(s))}</span>${i<steps.length-1?'<span class="flow-arrow">→</span>':''}`).join('');
  return `<div class="flow-title">${escapeHtml(f.title_zh||f.title_en||'流程')}</div><div class="flow-lane">${lane||'<span class="empty">无步骤</span>'}</div>`;
}

// ---- module dependency graph (SVG, root only) ----
const STATUS_COLOR={implemented:'#1f8a63',partial:'#c8860d',not_found:'#c0392b',unknown:'#8a928c'};
function moduleStatus(mod){ const n=byNode.get(mod); return n?statusOf(n):'unknown'; }
function dependencyGraph(deps){
  const mods=[]; const seen=new Set();
  deps.forEach(d=>{[d.src,d.dst].forEach(m=>{ const top=String(m||'').split('.')[0]; if(top&&!seen.has(top)){ seen.add(top); mods.push(top); } });});
  if(!mods.length) return '<div class="empty">无依赖</div>';
  const W=720, cx=W/2, cy=Math.max(200,mods.length*16), R=Math.min(cx,cy)-60;
  const pos={}; mods.forEach((m,i)=>{ const a=-Math.PI/2 + i*2*Math.PI/mods.length; pos[m]={x:cx+R*Math.cos(a), y:cy+R*Math.sin(a)}; });
  const edgeSet=new Set(); const edges=[];
  deps.forEach(d=>{ const s=String(d.src||'').split('.')[0], t=String(d.dst||'').split('.')[0]; if(s&&t&&s!==t&&pos[s]&&pos[t]){ const k=s+'>'+t; if(!edgeSet.has(k)){ edgeSet.add(k); edges.push([s,t]); } } });
  const lines=edges.map(([s,t])=>`<line x1="${pos[s].x.toFixed(0)}" y1="${pos[s].y.toFixed(0)}" x2="${pos[t].x.toFixed(0)}" y2="${pos[t].y.toFixed(0)}" stroke="#b9c4bc" stroke-width="1.2" marker-end="url(#arr)"/>`).join('');
  const nodes=mods.map(m=>{ const p=pos[m]; const c=STATUS_COLOR[moduleStatus(m)]; const lbl=(byNode.get(m)||{}).title_zh||m; return `<g><circle cx="${p.x.toFixed(0)}" cy="${p.y.toFixed(0)}" r="9" fill="${c}" stroke="#fff" stroke-width="1.5"/><text x="${p.x.toFixed(0)}" y="${(p.y-13).toFixed(0)}" text-anchor="middle">${escapeHtml(lbl)}</text></g>`; }).join('');
  return `<svg class="dep-graph" viewBox="0 0 ${W} ${cy*2}" preserveAspectRatio="xMidYMid meet"><defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#9aa89f"/></marker></defs>${lines}${nodes}</svg>`;
}
function rootOverview(){
  const flows=Object.values(DATA.flows||{});
  const deps=Object.values(DATA.dependencies||{});
  const flowHtml=flows.length?flows.slice(0,12).map(flowLane).join(''):'<div class="empty">无</div>';
  const depList=deps.length?deps.slice(0,20).map(d=>`<div class="dep-row"><b>${escapeHtml(formatNodeId(d.src))}</b> → <b>${escapeHtml(formatNodeId(d.dst))}</b><div class="muted">${escapeHtml(depText(d))}</div></div>`).join(''):'<div class="empty">无</div>';
  const legend=`<div class="legend"><span><i style="background:#1f8a63"></i>已实现</span><span><i style="background:#c8860d"></i>部分</span><span><i style="background:#c0392b"></i>未实现</span><span><i style="background:#8a928c"></i>未知</span></div>`;
  return `<div class="grid"><div class="panel accent wide"><h3>模块依赖关系图（全局）</h3>${legend}${dependencyGraph(deps)}</div><div class="panel accent"><h3>关键链路 / 执行流程</h3>${flowHtml}</div><div class="panel"><h3>模块依赖明细</h3>${depList}</div></div>`;
}

// ---- module child cards ----
function childCard(n){
  const concept = realConcept(n.summary_zh) || realConcept(n.concept_definition) || '';
  const mechs=(n.mechanisms||[]).slice(0,3).map(x=>badge(formatTag(x))).join('');
  return `<button class="card ${statusOf(n)}" data-id="${escapeHtml(n.node_id)}"><h4>${bilingual(n.title_zh||n.node_id, n.title_en)}</h4><div class="cpath">${escapeHtml(formatNodeId(n.node_id))}</div><p>${escapeHtml(concept)}</p><div>${badge(statusOf(n), statusOf(n)==='not_found'?'bad':statusOf(n)==='partial'?'partial':statusOf(n)==='implemented'?'ok':'unknown')} ${mechs}</div></button>`;
}

// ---- evolution history ----
function historyPanel(n){
  const claims=(n.claim_ids||[]).map(claimItem).join('') || '<div class="empty">无</div>';
  const evIds=n.evidence_ids||[];
  const choices=(n.design_choices||[]).map(x=>`<li>${escapeHtml(x)}</li>`).join('');
  let body=`<div class="panel accent wide"><h3>代码演进历史</h3><p>${escapeHtml(n.summary_zh||'')}</p>${(n.summary_en&&n.summary_en!==n.summary_zh)?`<p class="muted">${escapeHtml(n.summary_en)}</p>`:''}${choices?`<h3 style="margin-top:12px">演进要点</h3><ul class="list">${choices}</ul>`:''}</div>`;
  body+=`<div class="panel wide"><h3>历史结论 → Git 证据</h3>${claims}</div>`;
  if(evIds.length) body+=`<div class="panel wide"><h3>Git 证据</h3>${evIds.map(id=>evidenceBlock(id)).join('')}</div>`;
  return `<div class="grid">${body}</div>`;
}

// ---- main detail ----
function renderDetail(n){
  if(!n) return;
  const el=document.getElementById('detail');
  const isGroup = n.children && n.children.length;
  const isRoot = n.node_id==='KernelProject';
  const head=`<div class="node-title"><div><h2>${escapeHtml(n.title_zh||n.node_id)}</h2>${(n.title_en&&n.title_en!==n.title_zh)?`<div class="en">${escapeHtml(n.title_en)}</div>`:''}<div class="path">${escapeHtml(formatNodeId(n.node_id))}</div></div><div>${badge(statusOf(n), statusOf(n)==='not_found'?'bad':statusOf(n)==='partial'?'partial':statusOf(n)==='implemented'?'ok':'unknown')}${n.confidence?badge(n.confidence):''}</div></div>`;
  if(isGroup){
    // Global flows/deps belong ONLY to the project root; module groups show just their children.
    const overview = isRoot ? rootOverview() : '';
    el.innerHTML = head + overview + `<div class="cards">${n.children.map(childCard).join('')}</div>`;
    return;
  }
  if(n.node_id==='EvolutionHistory'){ el.innerHTML = head + historyPanel(n); return; }
  const concept = realConcept(n.summary_zh);
  const claimIds=n.claim_ids||[];
  const evIds=[]; const evSeen=new Set();
  claimIds.forEach(cid=>{ const c=DATA.claims[cid]; (c&&c.evidence_ids||[]).forEach(id=>{ if(!evSeen.has(id)){ evSeen.add(id); evIds.push(id); } }); });
  const claimsHtml = claimIds.length?claimIds.map(claimItem).join(''):'<div class="empty">无 claim</div>';
  const evHtml = evIds.length?evIds.map(id=>evidenceBlock(id)).join(''):'<div class="empty">无证据</div>';
  const deps=(n.dependency_ids||[]).map(id=>DATA.dependencies[id]).filter(Boolean);
  const depHtml = deps.length?`<ul class="list">${deps.map(d=>`<li><code>${escapeHtml(formatNodeId(d.src))}</code> → <code>${escapeHtml(formatNodeId(d.dst))}</code><br><span class="muted">${escapeHtml(depText(d))}</span></li>`).join('')}</ul>`:'<div class="empty">无</div>';
  const flows=(n.flow_ids||[]).map(id=>DATA.flows[id]).filter(Boolean);
  const flowHtml = flows.length?flows.map(flowLane).join(''):'';
  el.innerHTML = head + `
    ${concept?`<div class="panel accent" style="margin-top:14px"><h3>概念定义</h3><p>${escapeHtml(concept)}</p></div>`:''}
    <div class="grid">
      <div class="panel"><h3>抽象职责</h3>${list(n.responsibilities)}</div>
      <div class="panel"><h3>关键符号 / 定位</h3>${symbolTable(n.key_symbols)}</div>
      <div class="panel"><h3>设计取舍</h3>${list(n.design_choices)}</div>
      <div class="panel"><h3>模块依赖</h3>${depHtml}</div>
      ${flowHtml?`<div class="panel accent wide"><h3>关键链路</h3>${flowHtml}</div>`:''}
      <div class="panel wide"><h3>实现要点（可追溯到源码）</h3>${claimsHtml}</div>
      <div class="panel wide"><h3>源码证据</h3>${evHtml}</div>
    </div>`;
}

renderDetail(DATA.tree);
"""




