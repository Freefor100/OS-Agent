#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.judge_report import MODULE_IDS, validate_judge_report
from core.kernel_tree import ANALYSIS_ORDER_V2, ROOT_NODES_V2, node_scope, node_title_zh

IMPLEMENTATION_LABELS = {
    "complete": "完整", "partial": "部分", "minimal": "最低限度", "absent": "未发现实现",
    "not_applicable": "不适用", "unknown": "待确认",
}
ORIGINALITY_LABELS = {
    "independent": "独立实现", "substantial_rework": "实质重写", "incremental": "增量修改",
    "inherited": "主体继承", "not_applicable": "不适用", "unknown": "待确认",
}
CLAIM_LABELS = {
    "lineage": "来源关系", "difference": "实现差异", "independent_work": "独立工作",
    "implementation": "实现判断", "absence": "缺失判断", "risk": "复核风险",
}
EVIDENCE_KIND_LABELS = {
    "documentation": "文档说明", "function_definition": "函数定义", "type_definition": "数据结构",
    "macro_definition": "宏定义", "constant_definition": "常量定义", "config_entry": "配置项",
    "linker_symbol": "链接脚本", "assembly_label": "汇编入口", "source_span": "源码片段",
    "lsp_definition": "定义定位", "lsp_reference": "引用关系", "call_edge": "调用关系",
    "lsp_call_graph": "调用链", "git_history": "Git 历史", "formal_search": "正式检索",
    "scope_manifest": "代码范围", "negative_search": "负向搜索",
}

CSS = r"""
*{box-sizing:border-box}html,body{margin:0;height:100%;font-family:Inter,"Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;color:#18212f;background:#f3f6fa}
body{display:grid;grid-template-columns:310px minmax(0,1fr);overflow:hidden}.sidebar{height:100vh;background:#101c2c;color:#dce7f5;padding:22px 16px;overflow:auto;box-shadow:8px 0 28px #10203520;z-index:5}
.brand{padding:0 8px 18px;border-bottom:1px solid #ffffff18}.brand h1{font-size:20px;margin:0 0 7px}.brand p{margin:0;color:#9eb1c9;font-size:13px;line-height:1.6}.search{width:100%;margin:18px 0 12px;border:1px solid #ffffff20;background:#ffffff10;color:#fff;padding:11px 12px;border-radius:10px;outline:none}.search::placeholder{color:#9eb1c9}
.nav-home,.module-button,.node-button{width:100%;border:0;text-align:left;cursor:pointer;color:inherit;background:transparent}.nav-home{padding:11px;border-radius:9px;font-weight:700;margin-bottom:9px}.nav-home:hover,.nav-home.active,.module-button:hover,.module-button.active,.node-button:hover,.node-button.active{background:#ffffff12}
.module{border-top:1px solid #ffffff12;padding:7px 0}.module-button{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:10px 9px;border-radius:8px;font-weight:700}.module-count{font-size:11px;color:#92a9c4}.nodes{display:none;padding:2px 0 7px 8px}.module.open .nodes{display:block}.node-button{padding:8px 8px;border-radius:7px;margin:2px 0}.node-name{display:block;font-size:13px;margin-bottom:5px}.mini-badges{display:flex;gap:4px;flex-wrap:wrap}.mini{font-size:10px;padding:2px 5px;border-radius:5px;background:#ffffff10;color:#c8d5e6}.mini.impl{border-left:2px solid #55a7ff}.mini.orig{border-left:2px solid #d29cff}.mini.absent{opacity:.58}
.appendix-link{display:block;color:#d9e9ff;text-decoration:none;margin:18px 4px;padding:11px;border:1px solid #ffffff20;border-radius:9px;text-align:center}.content{height:100vh;overflow:auto;padding:28px 34px 70px}.topbar{display:none}.panel{display:none;max-width:1240px;margin:auto}.panel.active{display:block}.eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#607089;font-weight:800}.page-title{font-size:32px;line-height:1.25;margin:7px 0 10px}.lead{font-size:16px;color:#536278;line-height:1.8;max-width:900px}.card{background:#fff;border:1px solid #dfe6ef;border-radius:15px;padding:20px;margin:17px 0;box-shadow:0 8px 24px #24364b0a}.card h2,.card h3{margin-top:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.matrix{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.matrix-card{background:#fff;border:1px solid #dfe6ef;border-radius:12px;padding:15px;cursor:pointer}.matrix-card:hover{border-color:#7ea7d5;box-shadow:0 8px 20px #3d649414}.badges{display:flex;gap:8px;flex-wrap:wrap}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:5px 9px;font-weight:700;font-size:12px}.badge.impl{background:#e8f3ff;color:#17588f}.badge.orig{background:#f2ebff;color:#6935a5}.badge.confidence{background:#eef2f6;color:#4a596c}.claim{border-left:4px solid #517fbd;padding:14px 16px;margin:12px 0;background:#f8fafd;border-radius:0 10px 10px 0}.claim p{line-height:1.75;margin:8px 0}.evidence-link{display:inline-block;text-decoration:none;color:#245f9e;background:#e8f2fd;border-radius:6px;padding:3px 7px;font-size:12px;font-weight:700;margin:2px}.evidence-link:hover{background:#cfe6fb}.muted{color:#65758b}.section-list{padding-left:18px;line-height:1.85}.scope{padding:12px 14px;background:#edf3f8;border-radius:9px;color:#40536a;line-height:1.7}.risk{padding:12px 14px;background:#fff5ed;border-left:4px solid #e8904f;border-radius:8px;margin:8px 0}.absent-list{display:flex;gap:7px;flex-wrap:wrap}.absent-chip{background:#edf0f3;color:#697685;border-radius:7px;padding:5px 8px;font-size:12px}
.architecture{width:100%;height:auto;display:block;background:#f8fbfe;border-radius:12px}.evidence-section{max-width:1240px;margin:55px auto 0;padding-top:25px;border-top:2px solid #dce5ef}.evidence-card{background:#fff;border:1px solid #dfe6ef;border-radius:11px;margin:10px 0}.evidence-card summary{cursor:pointer;padding:15px 17px;font-weight:700}.evidence-body{padding:0 17px 17px}.evidence-body pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#111c2a;color:#d9e7f5;padding:14px;border-radius:8px;line-height:1.55}.crumb{color:#6d7c90;font-size:13px}.provenance-action{display:inline-block;background:#183b64;color:#fff;text-decoration:none;padding:10px 14px;border-radius:8px;font-weight:700;margin-top:9px}.drawer-button{display:none}
@media(max-width:1050px){body{grid-template-columns:270px minmax(0,1fr)}.content{padding:24px}.matrix{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){body{display:block;overflow:auto}.sidebar{position:fixed;left:-320px;width:300px;transition:left .2s}.sidebar.open{left:0}.content{height:auto;overflow:visible;padding:68px 16px 45px}.topbar{display:flex;position:fixed;top:0;left:0;right:0;height:54px;align-items:center;padding:0 15px;background:#101c2c;color:#fff;z-index:4}.drawer-button{display:block;border:0;background:#ffffff18;color:#fff;padding:7px 10px;border-radius:7px}.grid,.matrix{grid-template-columns:1fr}.page-title{font-size:25px}}
"""

JS = r"""
const panels=[...document.querySelectorAll('.panel')], nav=[...document.querySelectorAll('[data-view]')];
function openView(view, push=true){
  panels.forEach(x=>x.classList.toggle('active',x.dataset.panel===view));
  nav.forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  if(view.startsWith('node:')||view.startsWith('module:')){
    const id=view.split(':')[1], btn=document.querySelector(`[data-view="${CSS.escape(view)}"]`);
    if(btn){const module=btn.closest('.module'); if(module)module.classList.add('open'); btn.scrollIntoView({block:'nearest'});}
    if(push)history.replaceState(null,'','#'+(view.startsWith('node:')?'node=':'module=')+encodeURIComponent(id));
  }else if(push)history.replaceState(null,'','#overview');
  document.querySelector('.content').scrollTo({top:0,behavior:'smooth'});
  document.querySelector('.sidebar').classList.remove('open');
}
nav.forEach(x=>x.addEventListener('click',()=>openView(x.dataset.view)));
document.querySelectorAll('.module-button').forEach(x=>x.addEventListener('dblclick',()=>x.closest('.module').classList.toggle('open')));
document.querySelector('.search').addEventListener('input',e=>{
  const q=e.target.value.trim().toLowerCase();
  document.querySelectorAll('.node-button').forEach(x=>x.style.display=!q||x.dataset.search.includes(q)?'block':'none');
  document.querySelectorAll('.module').forEach(x=>{const hit=!q||x.dataset.search.includes(q)||[...x.querySelectorAll('.node-button')].some(n=>n.style.display!=='none');x.style.display=hit?'block':'none';if(q&&hit)x.classList.add('open')});
});
document.querySelectorAll('.evidence-link').forEach(x=>x.addEventListener('click',e=>{e.preventDefault();const card=document.getElementById(x.dataset.evidence);card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}));
document.querySelector('.drawer-button').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
const hash=decodeURIComponent(location.hash.slice(1)); if(hash.startsWith('node='))openView('node:'+hash.slice(5),false); else if(hash.startsWith('module='))openView('module:'+hash.slice(7),false); else openView('overview',false);
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render(report: dict[str, Any]) -> str:
    errors = validate_judge_report(report, require_complete=True)
    if errors:
        raise ValueError("judge report validation failed: " + "; ".join(errors))
    evidence = _read_evidence(report["evidence_store"])
    used = sorted({eid for claim in report["claims"] for eid in claim.get("evidence_ids") or []})
    evidence_labels = {eid: f"E{index:03d}" for index, eid in enumerate(used, 1)}
    evidence_tags = {eid: _evidence_short_tag(evidence[eid]) for eid in used}
    claims = {x["claim_id"]: x for x in report["claims"]}
    node_reviews = {x["node_id"]: x for x in report["node_reviews"]}
    modules = {x["module_id"]: x for x in report["module_reviews"]}
    work = report["work"]["display_name"]
    reference = report["reference"]["display_name"]
    sidebar = _sidebar(report, node_reviews, claims, modules)
    panels = [_overview_panel(report, node_reviews, modules, claims, evidence_labels)]
    panels += [_module_panel(module_id, modules[module_id], node_reviews, claims, evidence_labels, evidence_tags) for module_id in MODULE_IDS]
    panels += [_node_panel(report, node_id, node_reviews[node_id], claims, evidence_labels, evidence_tags) for node_id in ANALYSIS_ORDER_V2]
    evidence_html = _evidence_section(used, evidence, evidence_labels, work, reference, report)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(work)} 内核实现评审报告</title><style>{CSS}</style></head><body>
<aside class="sidebar">{sidebar}</aside><div class="topbar"><button class="drawer-button">目录</button><strong style="margin-left:12px">{esc(work)} 评审报告</strong></div>
<main class="content">{''.join(panels)}{evidence_html}</main><script>{JS}</script></body></html>"""


def _sidebar(report: dict[str, Any], reviews: dict[str, dict[str, Any]], claims: dict[str, dict[str, Any]],
             modules: dict[str, dict[str, Any]]) -> str:
    expanded = set((report.get("report_highlights") or {}).get("expanded_module_ids") or [])
    chunks = [f"""<div class="brand"><h1>{esc(report['work']['display_name'])} 评审报告</h1>
<p>与 {esc(report['reference']['display_name'])} 的来源关系、实现差异与独立工作评审</p></div>
<input class="search" placeholder="搜索模块、节点或结论"><button class="nav-home" data-view="overview">总体结果与架构</button>"""]
    for module_id, children in ROOT_NODES_V2.items():
        nodes = [module_id] if not children else [f"{module_id}.{child}" for child in children]
        node_html = []
        module_review = modules.get(module_id) or {}
        search_parts = [module_id, node_title_zh(module_id), module_review.get("overview", "")]
        for node_id in nodes:
            review = reviews[node_id]
            node_claims = [claims[x] for x in review.get("claim_ids") or [] if x in claims]
            search_text = " ".join([node_id, node_title_zh(node_id), review.get("overview", ""), *[x.get("statement", "") for x in node_claims]]).lower()
            impl = review["implementation_degree"]["level"]
            orig = review["originality"]["level"]
            absent = " absent" if impl in {"absent", "not_applicable"} else ""
            node_html.append(f"""<button class="node-button{absent}" data-view="node:{esc(node_id)}" data-search="{esc(search_text)}">
<span class="node-name">{esc(node_title_zh(node_id))}</span><span class="mini-badges"><span class="mini impl">实现：{esc(IMPLEMENTATION_LABELS[impl])}</span><span class="mini orig">原创：{esc(ORIGINALITY_LABELS[orig])}</span></span></button>""")
            search_parts.append(search_text)
        view = f"node:{module_id}" if module_id == "Metadata" else f"module:{module_id}"
        complete = sum(reviews[x]["implementation_degree"]["level"] == "complete" for x in nodes)
        original = sum(reviews[x]["originality"]["level"] in {"independent", "substantial_rework"} for x in nodes)
        chunks.append(f"""<section class="module{' open' if module_id in expanded else ''}" data-search="{esc(' '.join(search_parts).lower())}">
<button class="module-button" data-view="{esc(view)}"><span>{esc(node_title_zh(module_id))}</span><span class="module-count">完整 {complete}/{len(nodes)} · 独立/重写 {original}</span></button>
<div class="nodes">{''.join(node_html)}</div></section>""")
    chunks.append(f'<a class="appendix-link" href="{esc(report.get("provenance_href") or "provenance.html")}" target="_blank">打开函数级技术溯源附录</a>')
    return "".join(chunks)


def _overview_panel(report: dict[str, Any], reviews: dict[str, dict[str, Any]], modules: dict[str, dict[str, Any]],
                    claims: dict[str, dict[str, Any]], labels: dict[str, str]) -> str:
    assessment = report["overall_assessment"]
    matrix = []
    for module_id in MODULE_IDS:
        children = ROOT_NODES_V2[module_id]
        nodes = [module_id] if not children else [f"{module_id}.{child}" for child in children]
        complete = sum(reviews[x]["implementation_degree"]["level"] == "complete" for x in nodes)
        independent = sum(reviews[x]["originality"]["level"] in {"independent", "substantial_rework"} for x in nodes)
        matrix.append(f"""<article class="matrix-card" data-view="module:{esc(module_id)}"><strong>{esc(node_title_zh(module_id))}</strong>
<p class="muted">{len(nodes)} 个节点 · 完整 {complete} · 独立/实质重写 {independent}</p></article>""")
    return f"""<section class="panel" data-panel="overview"><div class="eyebrow">Judge-facing assessment</div>
<h1 class="page-title">{esc(report['work']['display_name'])} 内核实现评审报告</h1><p class="lead">{esc(assessment['summary'])}</p>
<div class="grid"><article class="card"><h2>来源与演进结论</h2><p>{esc(assessment['source_relation'])}</p></article>
<article class="card"><h2>评委重点复核</h2>{_list(assessment['review_focus'])}</article></div>
<div class="grid"><article class="card"><h3>主要继承部分</h3>{_list(assessment['main_inherited'])}</article>
<article class="card"><h3>实质性修改部分</h3>{_list(assessment['main_modified'])}</article>
<article class="card"><h3>相对独立实现部分</h3>{_list(assessment['main_independent'])}</article>
<article class="card"><h3>缺失、退化与风险</h3>{_list(assessment['incomplete_or_risks'])}</article></div>
<article class="card"><h2>静态内核架构图</h2>{_architecture_svg(assessment.get('architecture_edges') or [])}
{_architecture_edge_list(assessment.get('architecture_edges') or [])}</article>
<h2>框架实现度与原创度总览</h2><div class="matrix">{''.join(matrix)}</div></section>"""


def _module_panel(module_id: str, review: dict[str, Any], node_reviews: dict[str, dict[str, Any]],
                  claims: dict[str, dict[str, Any]], labels: dict[str, str], tags: dict[str, str]) -> str:
    children = ROOT_NODES_V2[module_id]
    nodes = [module_id] if not children else [f"{module_id}.{child}" for child in children]
    cards, absent = [], []
    for node_id in nodes:
        row = node_reviews[node_id]
        impl, orig = row["implementation_degree"]["level"], row["originality"]["level"]
        if impl in {"absent", "not_applicable"}:
            absent.append(node_title_zh(node_id))
        cards.append(f"""<article class="matrix-card" data-view="node:{esc(node_id)}"><strong>{esc(node_title_zh(node_id))}</strong>
<div class="badges" style="margin-top:8px"><span class="badge impl">实现：{esc(IMPLEMENTATION_LABELS[impl])}</span><span class="badge orig">原创：{esc(ORIGINALITY_LABELS[orig])}</span></div></article>""")
    featured = [claims[x] for x in review.get("featured_claim_ids") or [] if x in claims]
    chains = "".join(_key_chain(chain, labels, tags) for chain in review.get("key_chains") or [])
    return f"""<section class="panel" data-panel="module:{esc(module_id)}"><div class="crumb">总体结果 / {esc(node_title_zh(module_id))}</div>
<h1 class="page-title">{esc(node_title_zh(module_id))}</h1><p class="lead">{esc(review['overview'])}</p>
<div class="grid"><article class="card"><h3>相比参考作品的主要变化</h3><p>{esc(review['difference_summary'])}</p></article>
<article class="card"><h3>原创工作集中位置</h3><p>{esc(review['original_work_summary'])}</p></article>
<article class="card"><h3>实现完整程度与缺失能力</h3><p>{esc(review['implementation_summary'])}</p></article>
<article class="card"><h3>未实现或不适用节点</h3><div class="absent-list">{''.join(f'<span class="absent-chip">{esc(x)}</span>' for x in absent) or '<span class="muted">无</span>'}</div></article></div>
<h2>关键链路</h2>{chains}
<h2>重点结论</h2>{''.join(_claim_card(x, labels, tags) for x in featured) or '<p class="muted">本模块未单独置顶结论，节点页仍保留完整评审。</p>'}
<h2>节点评价矩阵</h2><div class="matrix">{''.join(cards)}</div></section>"""


def _node_panel(report: dict[str, Any], node_id: str, review: dict[str, Any], claims: dict[str, dict[str, Any]],
                labels: dict[str, str], tags: dict[str, str]) -> str:
    impl, orig = review["implementation_degree"], review["originality"]
    node_claims = [claims[x] for x in review.get("claim_ids") or [] if x in claims]
    risks = "".join(f'<div class="risk">{esc(x)}</div>' for x in review.get("risks") or []) or '<p class="muted">当前没有额外风险项。</p>'
    href = report.get("provenance_href") or "provenance.html"
    refs = review.get("provenance_refs") or []
    if refs and refs[0].get("target_file"):
        href += "#file:" + refs[0]["target_file"]
    return f"""<section class="panel" data-panel="node:{esc(node_id)}"><div class="crumb">{esc(node_title_zh(node_id.split(".",1)[0]))} / {esc(node_title_zh(node_id))}</div>
<h1 class="page-title">{esc(node_title_zh(node_id))}</h1><div class="scope"><strong>Scope：</strong>{esc(node_scope(node_id))}</div>
<div class="grid"><article class="card"><div class="badges"><span class="badge impl">实现：{esc(IMPLEMENTATION_LABELS[impl['level']])}</span></div><h3>实现度判断</h3><p>{esc(impl['rationale'])}</p></article>
<article class="card"><div class="badges"><span class="badge orig">原创：{esc(ORIGINALITY_LABELS[orig['level']])}</span></div><h3>原创度判断</h3><p>{esc(orig['rationale'])}</p></article></div>
<article class="card"><h2>{esc(report['work']['display_name'])} 中如何实现</h2><p>{esc(review['overview'])}</p></article>
<article class="card"><h2>与 {esc(report['reference']['display_name'])} 的差异</h2><p>{esc(review['difference_from_reference'])}</p></article>
<h2>Agent Claims</h2>{''.join(_claim_card(x, labels, tags) for x in node_claims)}
<article class="card"><h2>风险、缺失与不确定项</h2>{risks}<a class="provenance-action" href="{esc(href)}#search={esc(node_title_zh(node_id))}" target="_blank">打开函数级技术溯源</a></article></section>"""


def _claim_card(claim: dict[str, Any], labels: dict[str, str], tags: dict[str, str]) -> str:
    links = "".join(f'<a class="evidence-link" href="#{esc(labels[eid])}" data-evidence="evidence-{esc(labels[eid])}">{esc(tags[eid])} {esc(labels[eid])}</a>' for eid in claim.get("evidence_ids") or [])
    return f"""<article class="claim"><div class="badges"><span class="badge confidence">{esc(CLAIM_LABELS[claim['claim_type']])}</span>
<span class="badge confidence">置信度：{esc(claim['confidence'])}</span></div><p>{esc(claim['statement'])}</p><div>{links}</div></article>"""


def _key_chain(chain: dict[str, Any], labels: dict[str, str], tags: dict[str, str]) -> str:
    links = "".join(f'<a class="evidence-link" href="#{esc(labels[eid])}" data-evidence="evidence-{esc(labels[eid])}">{esc(tags[eid])} {esc(labels[eid])}</a>'
                    for eid in chain.get("evidence_ids") or [] if eid in labels)
    nodes = " → ".join(node_title_zh(node_id) for node_id in chain.get("node_ids") or [])
    return f"""<article class="card"><h3>{esc(chain.get('title'))}</h3><p class="muted">{esc(nodes)}</p>
<p>{esc(chain.get('explanation'))}</p><div>{links}</div></article>"""


def _evidence_section(used: list[str], records: dict[str, dict[str, Any]], labels: dict[str, str], work: str,
                      reference: str, report: dict[str, Any]) -> str:
    target_commit = (report["work"].get("snapshot") or {}).get("commit")
    reference_commit = (report["reference"].get("snapshot") or {}).get("commit")
    cards = []
    for eid in used:
        row = records[eid]
        commit = (row.get("metadata") or {}).get("snapshot_commit")
        owner = work if commit == target_commit else reference if commit == reference_commit else "检索与审计流程"
        location = f"{row.get('path') or ''}:{row.get('line_start') or ''}".rstrip(":")
        kind_label = EVIDENCE_KIND_LABELS.get(row.get("kind"), row.get("kind"))
        source_tag = "文档" if row.get("kind") == "documentation" else "程序事实" if row.get("kind") in {"formal_search", "negative_search", "scope_manifest"} else "源码/结构"
        cards.append(f"""<details class="evidence-card" id="evidence-{esc(labels[eid])}"><summary>{esc(labels[eid])} · [{esc(source_tag)}] [{esc(kind_label)}] · {esc(owner)} · {esc(row.get('label') or '')}</summary>
<div class="evidence-body"><p><strong>作品/来源：</strong>{esc(owner)}　<strong>commit：</strong><code>{esc(commit or '')}</code><br>
<strong>位置：</strong>{esc(location or '结构化审计记录')}　<strong>类型：</strong>{esc(kind_label)}　<strong>标签：</strong>{esc(source_tag)}　<strong>验证：</strong>{'已验证' if row.get('verified') else '未验证'}</p>
<pre>{esc(row.get('excerpt') or _evidence_summary(row))}</pre></div></details>""")
    return f'<section class="evidence-section"><h2>Evidence 源码与审计记录</h2><p class="muted">正文仅引用证据编号。展开后查看已验证源码片段或结构化检索结果。</p>{"".join(cards)}</section>'


def _evidence_summary(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    if row.get("kind") == "negative_search":
        return f"完整覆盖：{metadata.get('coverage_complete')}；扫描文件：{metadata.get('scanned_files')}；匹配数：{metadata.get('matches')}"
    if row.get("kind") == "formal_search":
        return f"正式检索排名：{metadata.get('rank')}；候选：{metadata.get('candidate_repo')}@{metadata.get('candidate_commit')}"
    return str(row.get("query") or row.get("label") or "已验证结构化证据")


def _evidence_short_tag(row: dict[str, Any]) -> str:
    kind = row.get("kind")
    if kind == "documentation":
        return "文档证据"
    if kind in {"formal_search", "negative_search", "scope_manifest", "git_history"}:
        return "审计证据"
    if kind in {"call_edge", "lsp_call_graph", "lsp_reference"}:
        return "链路证据"
    return "源码证据"


def _read_evidence(path: str) -> dict[str, dict[str, Any]]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        row = json.loads(line)
        out[row["evidence_id"]] = row
    return out


def _list(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    return '<ul class="section-list">' + "".join(f"<li>{esc(x)}</li>" for x in rows) + "</ul>"


def _architecture_svg(edges: list[dict[str, Any]]) -> str:
    modules = [node_title_zh(module_id) for module_id in MODULE_IDS]
    boxes = []
    centers = {}
    for i, name in enumerate(modules):
        col, row = i % 4, i // 4
        x, y = 32 + col * 205, 48 + row * 102
        centers[MODULE_IDS[i]] = (x + 84, y + 28)
        boxes.append(f'<rect x="{x}" y="{y}" width="168" height="56" rx="11" fill="#ffffff" stroke="#7da1c8"/><text x="{x+84}" y="{y+33}" text-anchor="middle" font-size="13" fill="#233c58">{esc(name)}</text>')
    arrows = []
    for edge in edges:
        start, end = centers.get(edge.get("from_module")), centers.get(edge.get("to_module"))
        if start and end:
            arrows.append(f'<path d="M{start[0]} {start[1]} L{end[0]} {end[1]}" stroke="#7894b3" stroke-width="1.8" fill="none" marker-end="url(#a)"/>')
    return f"""<svg class="architecture" viewBox="0 0 850 480" role="img" aria-label="静态内核架构图"><defs><marker id="a" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#7894b3"/></marker></defs>
<rect x="14" y="16" width="822" height="438" rx="18" fill="#eef5fb" stroke="#c9d8e7"/>{''.join(arrows)}{''.join(boxes)}
<text x="32" y="438" font-size="12" fill="#60758c">模块边界：圆角框　调用/依赖关系：箭头　外部依赖：不进入作品实现度与原创度统计</text></svg>"""


def _architecture_edge_list(edges: list[dict[str, Any]]) -> str:
    rows = [f"{node_title_zh(edge['from_module'])} → {node_title_zh(edge['to_module'])}：{edge['label']}" for edge in edges]
    return "<h3>架构关系说明</h3>" + _list(rows)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: judge_report.py <report.json> <report.html>")
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    main()
