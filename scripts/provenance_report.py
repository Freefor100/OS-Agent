#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.provenance_report import validate_provenance

STATUS_LABELS = {
    "exact_copied": "完全一致",
    "renamed_exact": "改名一致",
    "modified_candidate": "修改候选",
    "target_only": "zmz 中新增的函数候选",
    "ambiguous": "需要技术复核",
}

CSS = r"""
*{box-sizing:border-box}html,body{height:100%;margin:0;font-family:Inter,"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:#182431;background:#f4f7fa}
body{display:grid;grid-template-columns:320px minmax(0,1fr);overflow:hidden}.sidebar{height:100vh;overflow:auto;background:#172536;color:#dce8f5;padding:20px}.sidebar h1{font-size:19px;margin:0 0 7px}.sidebar p{font-size:12px;color:#9db0c5;line-height:1.6}
input,select{width:100%;border:1px solid #ffffff22;background:#ffffff10;color:#fff;padding:10px;border-radius:8px;margin:6px 0;outline:none}select option{color:#172536}.tree-dir{margin-top:15px;padding-top:10px;border-top:1px solid #ffffff16}.tree-dir strong{font-size:12px;color:#9db4cc}.file-button,.overview-button,.unmatched-button{width:100%;border:0;background:transparent;color:inherit;text-align:left;padding:8px;border-radius:7px;cursor:pointer;font-size:12px}.file-button:hover,.file-button.active,.overview-button:hover,.overview-button.active,.unmatched-button:hover,.unmatched-button.active{background:#ffffff12}
.content{height:100vh;overflow:auto;padding:28px 34px 70px}.panel{display:none;max-width:1250px;margin:auto}.panel.active{display:block}.page-title{font-size:29px;margin:5px 0}.muted{color:#66788d}.card{background:#fff;border:1px solid #dfe6ee;border-radius:13px;padding:18px;margin:15px 0;box-shadow:0 8px 22px #20364c0a}.counts{display:flex;gap:8px;flex-wrap:wrap}.pill{font-size:12px;border-radius:999px;padding:5px 8px;background:#edf3f8}.function{border-top:1px solid #e3e9ef;padding:12px 0}.function summary{cursor:pointer;font-weight:700}.status{font-size:11px;border-radius:5px;padding:3px 6px;margin-left:7px;background:#eaf1f7;color:#3f5975}.source-line{font-size:12px;color:#60748a;margin-top:5px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid #e5ebf0;vertical-align:top;font-size:13px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#111d2a;color:#d9e8f5;padding:13px;border-radius:8px;line-height:1.5}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}.candidate{padding:9px;background:#f3f7fa;border-radius:7px;margin:6px 0}.signal{font-family:ui-monospace,monospace;font-size:11px;color:#52657a}
@media(max-width:800px){body{display:block;overflow:auto}.sidebar{height:auto;position:relative}.content{height:auto;overflow:visible;padding:18px}.pair{grid-template-columns:1fr}}
"""

JS = r"""
const panels=[...document.querySelectorAll('.panel')], buttons=[...document.querySelectorAll('[data-view]')];
function openView(view){panels.forEach(x=>x.classList.toggle('active',x.dataset.panel===view));buttons.forEach(x=>x.classList.toggle('active',x.dataset.view===view));history.replaceState(null,'','#'+encodeURIComponent(view));document.querySelector('.content').scrollTo({top:0,behavior:'smooth'});}
buttons.forEach(x=>x.addEventListener('click',()=>openView(x.dataset.view)));
function filter(){const q=document.querySelector('#q').value.toLowerCase(), status=document.querySelector('#status').value;document.querySelectorAll('.file-button').forEach(x=>{const hit=(!q||x.dataset.search.includes(q))&&(!status||x.dataset.status.includes(status));x.style.display=hit?'block':'none'});}
document.querySelector('#q').addEventListener('input',filter);document.querySelector('#status').addEventListener('change',filter);
const hash=decodeURIComponent(location.hash.slice(1)); if(hash.startsWith('file:'))openView(hash); else openView('overview');
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render(report: dict[str, Any]) -> str:
    errors = validate_provenance(report)
    if errors:
        raise ValueError("provenance report validation failed: " + "; ".join(errors))
    work, reference = report["work"]["display_name"], report["reference"]["display_name"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in report["files"]:
        grouped[row.get("directory") or "."].append(row)
    nav = [f"""<h1>函数级技术溯源</h1><p>{esc(work)} 与 {esc(reference)} 的确定性函数匹配、来源候选与源码对照。此附录不作原创度或实现度判断。</p>
<input id="q" placeholder="搜索文件或函数"><select id="status"><option value="">全部状态</option>{''.join(f'<option value="{esc(k)}">{esc(v)}</option>' for k,v in STATUS_LABELS.items())}</select>
<button class="overview-button" data-view="overview">确定性对比概要</button><button class="unmatched-button" data-view="unmatched">{esc(reference)} 中未找到对应实现</button>"""]
    for directory, files in sorted(grouped.items()):
        nav.append(f'<section class="tree-dir"><strong>{esc(directory)}</strong>')
        for row in sorted(files, key=lambda x: x["target_file"]):
            names = " ".join((x.get("target") or {}).get("symbol") or "" for x in row["functions"])
            statuses = " ".join(x.get("raw_status") or "" for x in row["functions"])
            nav.append(f'<button class="file-button" data-view="file:{esc(row["target_file"])}" data-search="{esc((row["target_file"]+" "+names).lower())}" data-status="{esc(statuses)}">{esc(Path(row["target_file"]).name)}</button>')
        nav.append("</section>")
    panels = [_overview(report), _unmatched(report)]
    panels += [_file_panel(row, work, reference) for row in report["files"]]
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(work)} 函数级技术溯源</title><style>{CSS}</style></head><body><aside class="sidebar">{''.join(nav)}</aside>
<main class="content">{''.join(panels)}</main><script>{JS}</script></body></html>"""


def _overview(report: dict[str, Any]) -> str:
    summary = report["overview"]["summary"]
    pills = "".join(f'<span class="pill">{esc(STATUS_LABELS.get(key,key))}：{value}</span>' for key, value in summary.items() if key != "base_only")
    hot = "".join(f"<tr><td>{esc(x['target_file'])}</td><td>{x.get('modified_candidate',0)}</td><td>{x.get('target_only',0)}</td><td>{x.get('source_file_count',0)}</td></tr>" for x in report["overview"].get("hotspots") or [])
    return f"""<section class="panel" data-panel="overview"><h1 class="page-title">确定性函数对比概要</h1>
<p class="muted">本页只展示程序计算的匹配事实与候选信号，不自动生成来源性质、原创度或实现度结论。</p>
<article class="card"><div class="counts">{pills}</div><p>作品函数单元 {report['overview']['target_units']}，参考作品函数单元 {report['overview']['source_units']}。</p></article>
<article class="card"><h2>技术复核热点</h2><table><tr><th>文件</th><th>修改候选</th><th>新增候选</th><th>来源文件数</th></tr>{hot}</table></article></section>"""


def _unmatched(report: dict[str, Any]) -> str:
    reference = report["reference"]["display_name"]
    body = "".join(f"<details class='card'><summary><code>{esc(row['base_file'])}</code> · {row['base_only']} 个函数</summary><p>{esc(', '.join(row['symbols']))}</p></details>" for row in report["reference_unmatched_files"])
    return f"""<section class="panel" data-panel="unmatched"><h1 class="page-title">{esc(reference)} 中存在、{esc(report['work']['display_name'])} 未找到确定性对应实现的函数</h1>
<p class="muted">这里仅表示函数级确定性匹配未建立，不能单独证明整个机制被删除。</p>{body or '<article class="card">未发现此类函数。</article>'}</section>"""


def _file_panel(row: dict[str, Any], work: str, reference: str) -> str:
    counts = "".join(f'<span class="pill">{esc(STATUS_LABELS.get(key,key))}：{row.get(key,0)}</span>' for key in STATUS_LABELS if row.get(key, 0))
    sources = "".join(f"<tr><td>{esc(x['source_repo'])}/{esc(x['source_file'])}</td><td>{x['matched_units']}</td><td>{x['affinity']:.3f}</td><td>{x['average_pair_score']:.3f}</td></tr>" for x in row["sources"])
    functions = "".join(_function(x, work, reference) for x in row["functions"])
    return f"""<section class="panel" data-panel="file:{esc(row['target_file'])}"><h1 class="page-title"><code>{esc(row['target_file'])}</code></h1>
<article class="card"><div class="counts">{counts}</div><h3>候选来源文件</h3><table><tr><th>来源</th><th>匹配函数</th><th>文件关联度</th><th>平均匹配信号</th></tr>{sources or '<tr><td colspan="4">无候选来源</td></tr>'}</table></article>
<article class="card"><h2>函数列表与源码对照</h2>{functions}</article></section>"""


def _function(row: dict[str, Any], work: str, reference: str) -> str:
    target = row.get("target") or {}
    primary = row.get("primary_source") or {}
    candidates = "".join(f"""<div class="candidate"><strong>{esc(x['source_repo'])}/{esc(x['source_unit']['file'])}::{esc(x['source_unit']['symbol'])}</strong>
<div class="signal">匹配分数 {x['pair_score']:.3f} · {esc(json.dumps(x.get('signals') or {}, ensure_ascii=False, sort_keys=True))}</div></div>""" for x in row.get("candidates") or [])
    target_source = row.get("target_source") or {}
    source_snippets = row.get("candidate_sources") or []
    source = source_snippets[0] if source_snippets else {}
    pair = f"""<div class="pair"><div><h4>{esc(work)} 源码</h4><pre>{esc(target_source.get('content') or '源码片段不可用')}</pre></div>
<div><h4>{esc(reference)} / 来源候选源码</h4><pre>{esc(source.get('content') or '源码片段不可用')}</pre></div></div>"""
    source_label = "无确定性来源" if not primary else f"{primary.get('repo')}/{primary.get('file')}::{primary.get('symbol')}"
    return f"""<details class="function"><summary>{esc(target.get('symbol'))}<span class="status">{esc(STATUS_LABELS.get(row.get('raw_status'),row.get('raw_status')))}</span></summary>
<div class="source-line">{esc(work)} 第 {esc(target.get('line'))} 行 · 主要确定性来源：{esc(source_label)}</div>
<h4>候选来源与匹配信号</h4>{candidates or '<p class="muted">无候选来源。</p>'}{pair}</details>"""


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: provenance_report.py <provenance.json> <provenance.html>")
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    main()
