#!/usr/bin/env python3
"""HTML report shell generator.

Produces a structured HTML template with pre-computed data (contribution tables,
lineage, kernel tree skeleton with colors). The Agent fills in natural-language
analysis and node colors into the report_data.json, then renders to HTML.

Usage (by Agent via bash):
  # 1. generate the fixed 112-node skeleton JSON (empty slots to fill)
  python scripts/report.py skeleton <target> <report_data.json>

  # 2. (Agent edits report_data.json: fills color/stats/size_tokens/analysis + context)

  # 3. render the filled JSON to HTML
  python scripts/report.py render <report_data.json> <output_dir>

The skeleton's tree nodes carry title_zh + scope (fixed framework). The Agent
judges color from the fingerprint diff and fills it in — the script never decides
color or workload.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── CSS (embedded, consistent across all reports) ────────────────────

REPORT_CSS = """\
:root {
  --color-copied: #f9a825;     /* yellow — inherited from base */
  --color-modified: #c62828;   /* red — changed relative to base */
  --color-novel: #1565c0;      /* blue — student's own work */
  --color-external: #9e9e9e;   /* gray — not implemented / external dep */
  --color-bg: #fafafa;
  --color-card: #ffffff;
  --color-text: #263238;
  --color-muted: #78909c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Noto Sans SC', sans-serif; background: var(--color-bg); color: var(--color-text); line-height: 1.6; padding: 2rem; }
h1 { font-size: 1.8rem; margin-bottom: .5rem; }
h2 { font-size: 1.3rem; margin: 2rem 0 1rem; border-bottom: 2px solid #e0e0e0; padding-bottom: .3rem; }
h3 { font-size: 1.1rem; margin: 1rem 0 .5rem; }
.card { background: var(--color-card); border-radius: 8px; padding: 1.2rem; margin: 1rem 0; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: .8rem; }
.meta-item { display: flex; flex-direction: column; }
.meta-label { font-size: .8rem; color: var(--color-muted); text-transform: uppercase; }
.meta-value { font-size: 1.05rem; font-weight: 500; }
table { width: 100%; border-collapse: collapse; margin: .5rem 0; }
th, td { padding: .5rem .8rem; text-align: left; border-bottom: 1px solid #e0e0e0; font-size: .9rem; }
th { font-weight: 600; color: var(--color-muted); font-size: .8rem; text-transform: uppercase; }
.badge { display: inline-block; padding: .2rem .6rem; border-radius: 4px; font-size: .75rem; font-weight: 600; color: #fff; }
.badge-copied { background: var(--color-copied); }
.badge-modified { background: var(--color-modified); }
.badge-novel { background: var(--color-novel); }
.badge-external { background: var(--color-external); }
.node { border-left: 4px solid #e0e0e0; padding: .8rem 1rem; margin: .5rem 0; background: var(--color-card); border-radius: 0 6px 6px 0; }
.node-copied { border-left-color: var(--color-copied); }
.node-modified { border-left-color: var(--color-modified); }
.node-novel { border-left-color: var(--color-novel); }
.node-external { border-left-color: var(--color-external); }
.node-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: .5rem; }
.node-title { font-weight: 600; }
.node-scope { font-size: .8rem; color: var(--color-muted); margin: .2rem 0 .4rem; }
.comp-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: .3rem 0; background: #eceff1; }
.comp-seg { height: 100%; }
.disguise-flag { display: inline-block; background: #c62828; color: #fff; font-size: .72rem; font-weight: 600; padding: .15rem .5rem; border-radius: 4px; }
.node-stats { font-size: .8rem; color: var(--color-muted); }
.analysis { margin-top: .5rem; font-size: .9rem; }
.analysis-placeholder { color: var(--color-muted); font-style: italic; }
.context-list { list-style: none; padding: 0; }
.context-list li { padding: .3rem 0; border-bottom: 1px dashed #e0e0e0; font-size: .9rem; }
.warning-box { background: #fff3e0; border: 1px solid #ffcc02; border-radius: 6px; padding: 1rem; margin: 1rem 0; }
.warning-box h4 { color: #e65100; margin-bottom: .3rem; }
.legend { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0; }
.legend-item { display: flex; align-items: center; gap: .4rem; font-size: .85rem; }
.legend-swatch { width: 16px; height: 16px; border-radius: 3px; }
.mermaid { background: #f5f5f5; border-radius: 6px; padding: 1rem; margin: 1rem 0; overflow-x: auto; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #e0e0e0; font-size: .8rem; color: var(--color-muted); }
"""\
# ── helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def _pct(n: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{100 * n // total}%"


# status → (css color-var suffix, label)
_STATUS_META = {
    "copied": ("copied", "照搬"),
    "disguise": ("copied", "改名照搬"),  # disguise lives in the yellow family
    "modified": ("modified", "修改"),
    "novel": ("novel", "独创"),
}


def _dominant_color(node: dict) -> str:
    """Main color = the status with the largest share (占比最多者).

    Prefers an explicit `color` set by the Agent; otherwise derives from stats.
    disguise counts fold into the copied (yellow) family for the main color.
    Returns one of: copied / modified / novel / external.
    """
    c = (node.get("color") or "").strip().lower()
    if c in ("copied", "yellow"):
        return "copied"
    if c in ("modified", "red"):
        return "modified"
    if c in ("novel", "blue"):
        return "novel"
    if c in ("external", "gray", "grey", ""):
        # derive from stats if present
        stats = node.get("stats") or {}
        yellow = stats.get("copied", 0) + stats.get("disguise", 0)
        buckets = {"copied": yellow, "modified": stats.get("modified", 0),
                   "novel": stats.get("novel", 0)}
        top = max(buckets, key=lambda k: buckets[k])
        if buckets[top] > 0:
            return top
        return "external"
    return "external"


def _color_class(node: dict) -> str:
    return {"copied": "node-copied", "modified": "node-modified",
            "novel": "node-novel"}.get(_dominant_color(node), "node-external")


def _badge_class(color: str) -> str:
    m = {"copied": "badge-copied", "yellow": "badge-copied",
         "modified": "badge-modified", "red": "badge-modified",
         "novel": "badge-novel", "blue": "badge-novel"}
    return m.get(color, "badge-external")


def _composition_bar(stats: dict) -> str:
    """Stacked bar showing copied/disguise/modified/novel proportions.

    Shows the real mix so a 'partly implemented' node isn't hidden behind one color.
    """
    if not stats:
        return ""
    order = [("novel", "var(--color-novel)"), ("modified", "var(--color-modified)"),
             ("copied", "var(--color-copied)"), ("disguise", "var(--color-copied)")]
    total = sum(stats.get(k, 0) for k, _ in order)
    if total <= 0:
        return ""
    segs = []
    for key, col in order:
        n = stats.get(key, 0)
        if n <= 0:
            continue
        w = 100 * n / total
        # disguise gets a hatch overlay to flag renamed copies
        extra = ("background-image:repeating-linear-gradient(45deg,"
                 "rgba(0,0,0,.25) 0 4px,transparent 4px 8px);" if key == "disguise" else "")
        segs.append(f'<div class="comp-seg" style="width:{w:.1f}%;background:{col};{extra}" '
                    f'title="{key}={n}"></div>')
    return f'<div class="comp-bar">{"".join(segs)}</div>'


# ── section renderers ────────────────────────────────────────────────

def _render_meta(report: dict) -> str:
    meta = report.get("meta", {})
    items = [
        ("作品名称", meta.get("repo_name", "")),
        ("年份", str(meta.get("year", ""))),
        ("学校", meta.get("school", "")),
        ("队伍", meta.get("team", "")),
        ("赛事", meta.get("competition", "")),
        ("分析分支", meta.get("branch", "")),
        ("对比基准", meta.get("base", "无 — 独立分析")),
        ("生成时间", _now_iso()),
    ]
    rows = "\n".join(
        f'<div class="meta-item"><span class="meta-label">{label}</span><span class="meta-value">{value}</span></div>'
        for label, value in items
    )
    return f'<div class="card"><h2>作品元信息</h2><div class="meta-grid">{rows}</div></div>'


def _render_context(report: dict) -> str:
    """Render the cross-node live document: base verdict, inherited subsystems, findings."""
    ctx = report.get("context") or {}
    verdict = (ctx.get("base_verdict") or "").strip()
    inherited = ctx.get("inherited_subsystems") or []
    findings = ctx.get("findings") or []
    if not (verdict or inherited or findings):
        return ""

    parts = []
    if verdict:
        parts.append(f'<p><strong>血缘判定：</strong>{verdict}</p>')
    if inherited:
        parts.append('<p><strong>已继承子系统：</strong>' + "、".join(inherited) + '</p>')
    if findings:
        items = "\n".join(f"<li>{f}</li>" for f in findings)
        parts.append(f'<p><strong>关键发现：</strong></p><ul class="context-list">{items}</ul>')

    return f'<div class="card"><h2>分析上下文</h2>{"".join(parts)}</div>'


def _render_contribution(report: dict) -> str:
    summary = report.get("summary", {})
    total = sum(summary.values()) or 1
    rows = []
    for status, label, color in [
        ("copied", "COPIED — 照搬（同名同指纹）", "copied"),
        ("disguise", "DISGUISE — 改名拷贝（同指纹不同名）", "modified"),
        ("modified", "MODIFIED — 同名改动（不同指纹）", "modified"),
        ("novel", "NOVEL — 自研（无匹配）", "novel"),
    ]:
        n = summary.get(status, 0)
        rows.append(
            f'<tr><td><span class="badge badge-{color}">{status}</span></td>'
            f'<td>{label}</td>'
            f'<td style="text-align:right">{n}</td>'
            f'<td style="text-align:right">{_pct(n, total)}</td></tr>'
        )
    real = summary.get("modified", 0) + summary.get("novel", 0)
    return f"""\
<div class="card">
  <h2>贡献占比</h2>
  <table>
    <tr><th>分类</th><th>含义</th><th>函数数</th><th>占比</th></tr>
    {''.join(rows)}
    <tr style="font-weight:600;border-top:2px solid #e0e0e0">
      <td colspan="2">实质性工作 (MODIFIED + NOVEL)</td>
      <td style="text-align:right">{real}</td>
      <td style="text-align:right">{_pct(real, total)}</td>
    </tr>
  </table>
</div>"""


def _render_lineage(report: dict) -> str:
    candidates = report.get("lineage", [])
    if not candidates:
        return '<div class="card"><h2>血缘总览</h2><p>无相似候选</p></div>'

    rows = []
    for c in candidates[:10]:
        fw = " [框架]" if c.get("is_framework") else ""
        school = f' ({c.get("school", "")})' if c.get("school") else ""
        rows.append(
            f'<tr><td>{c["repo"]}{fw}</td>'
            f'<td style="text-align:right">{c["combined"]:.3f}</td>'
            f'<td style="text-align:right">{c.get("year", "")}{school}</td></tr>'
        )
    return f"""\
<div class="card">
  <h2>血缘总览 — Top-10 相似候选</h2>
  <table>
    <tr><th>候选作品</th><th>相似度 (combined)</th><th>年份 / 学校</th></tr>
    {''.join(rows)}
  </table>
</div>"""


def _render_tree(report: dict) -> str:
    """Render the 3-color kernel design tree from Agent-filled node data.

    Each node: main color = dominant status; a composition bar shows the real
    copied/modified/novel mix; a ⚠ flag marks renamed copies (disguise).
    """
    nodes = report.get("tree_nodes", [])
    if not nodes:
        return '<div class="card"><h2>内核设计树</h2><p>无节点数据</p></div>'

    legend = """\
<div class="legend">
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-novel)"></div> 独创实现 (NOVEL)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-modified)"></div> 实现但修改 (MODIFIED)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-copied)"></div> 实现照搬 (COPIED)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-copied);background-image:repeating-linear-gradient(45deg,rgba(0,0,0,.25) 0 4px,transparent 4px 8px)"></div> ⚠ 改名照搬 (DISGUISE)</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-external)"></div> 未实现 / 外部依赖</div>
</div>"""

    node_html_parts = []
    for node in nodes:
        node_id = node.get("id", "")
        title = node.get("title_zh", node_id)
        scope = node.get("scope", "")
        stats = node.get("stats") or {}
        dom = _dominant_color(node)
        analysis = (node.get("analysis") or "").strip()
        size = node.get("size_tokens", 0)

        # disguise flag: explicit field OR any disguise count in stats
        disguised = bool(node.get("disguise")) or stats.get("disguise", 0) > 0
        warn = ' <span class="disguise-flag" title="含改名照搬，疑似作弊">⚠ 改名照搬</span>' if disguised else ""

        badge = dom.upper() if dom != "external" else "—"
        comp = _composition_bar(stats)
        stat_text = ", ".join(f"{k}={v}" for k, v in stats.items() if v)
        size_text = f" · {size} tok" if size else ""
        scope_html = f'<div class="node-scope">{scope}</div>' if scope else ""

        if analysis:
            analysis_html = f'<div class="analysis">{analysis}</div>'
        else:
            analysis_html = ('<div class="analysis"><span class="analysis-placeholder">'
                             f'[待 Agent 填写 {title} 的分析]</span></div>')

        node_html_parts.append(f"""\
<div class="node {_color_class(node)}" data-node-id="{node_id}">
  <div class="node-header">
    <span class="node-title">{title} <code style="font-size:.75rem;color:var(--color-muted)">{node_id}</code></span>
    <span class="badge {_badge_class(dom)}">{badge}</span>{warn}
  </div>
  {scope_html}
  {comp}
  <div class="node-stats">{stat_text}{size_text}</div>
  {analysis_html}
</div>""")

    return f"""\
<div class="card">
  <h2>内核设计树</h2>
  {legend}
  {''.join(node_html_parts)}
</div>"""


def _render_mermaid_stub(report: dict) -> str:
    """Render the Mermaid architecture diagram.

    The Agent sets report.meta.mermaid with the actual Mermaid source.
    Falls back to a stub asking the Agent to provide one.
    """
    mermaid = (report.get("meta", {}).get("mermaid") or "").strip()
    if not mermaid:
        mermaid = (
            "graph TD\n"
            "  %% Agent: fill meta.mermaid in report_data.json with the actual\n"
            "  %% Mermaid diagram showing 14 subsystems with color-coded nodes\n"
            "  subgraph Legend\n"
            "    yellow[COPIED]:::copied\n"
            "    red[MODIFIED]:::modified\n"
            "    blue[NOVEL]:::novel\n"
            "  end\n"
            "  classDef copied fill:#f9a825,color:#fff\n"
            "  classDef modified fill:#c62828,color:#fff\n"
            "  classDef novel fill:#1565c0,color:#fff"
        )
    return f'<div class="card"><h2>架构图</h2><div class="mermaid"><pre>{mermaid}</pre></div></div>'


def _render_innovation(report: dict) -> str:
    innovations = report.get("innovations", [])
    if not innovations:
        return ""
    items = "\n".join(f"<li>{i}</li>" for i in innovations)
    return f"""\
<div class="card">
  <h2>创新功能区</h2>
  <p>超出标准 14 子系统的自研模块：</p>
  <ul>{items}</ul>
</div>"""


def _render_asm_statement(report: dict) -> str:
    asm = report.get("asm_coverage", {})
    if not asm:
        return ""
    return f"""\
<div class="card">
  <h2>汇编覆盖声明</h2>
  <table>
    <tr><th>汇编文件数</th><td>{asm.get('file_count', 0)}</td></tr>
    <tr><th>分析粒度</th><td>{asm.get('granularity', 'label-block')}</td></tr>
    <tr><th>已知局限</th><td>{asm.get('limitations', '无')}</td></tr>
  </table>
</div>"""


# ── main entry ───────────────────────────────────────────────────────

def render_html(report: dict) -> str:
    """Generate the complete HTML report shell.

    report dict structure:
      {
        "meta": {repo_name, year, school, team, competition, branch, base},
        "summary": {copied, disguise, modified, novel},
        "lineage": [{repo, combined, is_framework, year, school}, ...],
        "tree_nodes": [{id, title_zh, color, stats: {copied, modified, novel}},...],
        "innovations": ["GUI subsystem", "Wayland compositor"],
        "asm_coverage": {file_count, granularity, limitations},
      }
    """
    title = report.get("meta", {}).get("repo_name", "OS Analysis Report")
    sections = [
        _render_meta(report),
        _render_context(report),
        _render_contribution(report),
        _render_lineage(report),
        _render_tree(report),
        _render_mermaid_stub(report),
        _render_innovation(report),
        _render_asm_statement(report),
    ]

    html = f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — 内核分析报告</title>
<style>
{REPORT_CSS}
</style>
</head>
<body>
<h1>{title} — 内核设计分析报告</h1>
<p style="color:var(--color-muted)">OS-Agent 自动生成 · {_now_iso()}</p>

{''.join(sections)}

<footer>
  <p>OS-Agent Plagiarism Detection Pipeline · Generated {_now_iso()}</p>
  <p>14 subsystems, 112 leaf nodes · 3-color provenance coding</p>
</footer>
</body>
</html>"""
    return html


def compute_report_data(target: str, base: str | None = None,
                        compare_result: dict | None = None,
                        search_candidates: list[dict] | None = None,
                        metadata: dict | None = None,
                        branch: str = "",
                        context: dict | None = None) -> dict:
    """Build the report skeleton — a fixed 112-node JSON the Agent fills in.

    This is the SKELETON GENERATOR. It produces the report structure with empty
    slots; the Agent fills color/stats/size_tokens/analysis after judging the
    fingerprint diff. The script never decides color or workload.

    Each tree node carries:
      - title_zh, scope  (from the taxonomy — fixed framework)
      - color: ""        (Agent fills: copied/modified/novel/external, +disguise flag)
      - stats: {}        (Agent fills: {copied, disguise, modified, novel} counts)
      - size_tokens: 0   (Agent fills: total tokens of functions on this node)
      - analysis: ""     (Agent fills: natural-language description)

    `context` is the cross-node live document (base verdict, inherited subsystems,
    key findings) that the Agent updates batch-by-batch.
    """
    from core.kernel_tree import ANALYSIS_ORDER_V2, node_title_zh, node_scope

    report = {
        "meta": {
            "repo_name": target,
            "year": metadata.get("year", 0) if metadata else 0,
            "school": metadata.get("school", "") if metadata else "",
            "team": metadata.get("team", "") if metadata else "",
            "competition": metadata.get("competition", "") if metadata else "",
            "branch": branch,
            "base": base or "",
        },
        "context": context or {
            "base_verdict": "",        # 往届base→真增量 / 同届→互抄⚠ / 无→独立设计
            "inherited_subsystems": [],  # 已判定为继承自 base 的子系统
            "findings": [],            # 跨节点关键发现，前序批次喂后续
        },
        "summary": {},
        "lineage": [],
        "tree_nodes": [],
        "innovations": [],
        "asm_coverage": {},
    }

    if compare_result:
        report["summary"] = compare_result.get("summary", {})

    if search_candidates:
        report["lineage"] = [
            {"repo": c["repo"], "combined": c["combined"],
             "is_framework": c.get("is_framework", False),
             "year": c.get("year", 0), "school": c.get("school", "")}
            for c in (search_candidates or [])[:10]
        ]

    # Fixed 112-node skeleton with empty slots — Agent fills color/stats/analysis.
    for node_id in ANALYSIS_ORDER_V2:
        report["tree_nodes"].append({
            "id": node_id,
            "title_zh": node_title_zh(node_id),
            "scope": node_scope(node_id),
            "color": "",          # Agent fills after judging fingerprint diff
            "disguise": False,    # Agent sets True if node contains renamed copies
            "stats": {},          # Agent fills {copied, disguise, modified, novel}
            "size_tokens": 0,     # Agent fills total token size
            "analysis": "",       # Agent fills natural-language description
        })

    return report


# ── CLI ──────────────────────────────────────────────────────────────

def _usage() -> None:
    print("Usage:")
    print("  python scripts/report.py skeleton <target> <report_data.json> [branch]")
    print("      generate the fixed 112-node skeleton JSON (empty slots to fill)")
    print("  python scripts/report.py render <report_data.json> <output_dir>")
    print("      render a filled report_data.json to <output_dir>/index.html")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _usage()
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "skeleton":
        if len(sys.argv) < 4:
            _usage()
            sys.exit(1)
        target = sys.argv[2]
        out_path = sys.argv[3]
        branch = sys.argv[4] if len(sys.argv) > 4 else ""
        # try to enrich meta from xlsx metadata if available
        meta = None
        try:
            from core.metadata import MetadataManager
            mm = MetadataManager()
            m = mm.lookup_by_repo_name(target)
            if m:
                meta = {"year": m["year"], "school": m["school"],
                        "team": m["team_name"], "competition": m["competition"]}
        except Exception:
            pass
        data = compute_report_data(target, metadata=meta, branch=branch)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"Skeleton written to {out_path} ({len(data['tree_nodes'])} nodes)")

    elif mode == "render":
        if len(sys.argv) < 3:
            _usage()
            sys.exit(1)
        data_path = sys.argv[2]
        output_dir = sys.argv[3] if len(sys.argv) > 3 else ""
        with open(data_path) as f:
            data = json.load(f)
        html = render_html(data)
        if output_dir:
            out = Path(output_dir) / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html)
            print(f"Report written to {out}")
        else:
            print(html)

    else:
        # backward-compat: treat first arg as data path (old positional usage)
        data_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else ""
        with open(data_path) as f:
            data = json.load(f)
        html = render_html(data)
        if output_dir:
            out = Path(output_dir) / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html)
            print(f"Report written to {out}")
        else:
            print(html)
