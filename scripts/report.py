#!/usr/bin/env python3
"""HTML report shell generator.

Produces a structured HTML template with pre-computed data (contribution tables,
lineage, kernel tree skeleton with colors). The Agent fills in natural-language
analysis into <!-- AGENT_DESC --> markers.

Usage (by Agent via bash):
  python scripts/report.py --data report_data.json --output output/<target>/

The Agent reads the generated HTML, finds <!-- AGENT_DESC --> markers, and replaces
them with natural-language analysis for each kernel tree node.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

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
.node-stats { font-size: .8rem; color: var(--color-muted); }
.analysis { margin-top: .5rem; font-size: .9rem; }
.analysis-placeholder { color: var(--color-muted); font-style: italic; }
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

def _color_class(node: dict) -> str:
    """Determine the dominant color for a kernel tree node."""
    c = node.get("color", "")
    if c in ("copied", "yellow"):
        return "node-copied"
    if c in ("modified", "red"):
        return "node-modified"
    if c in ("novel", "blue"):
        return "node-novel"
    return "node-external"

def _badge_class(color: str) -> str:
    m = {"copied": "badge-copied", "yellow": "badge-copied",
         "modified": "badge-modified", "red": "badge-modified",
         "novel": "badge-novel", "blue": "badge-novel"}
    return m.get(color, "badge-external")


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
    """Render the 3-color kernel design tree with placeholders for Agent analysis."""
    nodes = report.get("tree_nodes", [])
    if not nodes:
        return '<div class="card"><h2>内核设计树</h2><p>无节点数据</p></div>'

    legend = """\
<div class="legend">
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-copied)"></div> COPIED — 继承自base</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-modified)"></div> MODIFIED — 相对base改动</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-novel)"></div> NOVEL — 自研</div>
  <div class="legend-item"><div class="legend-swatch" style="background:var(--color-external)"></div> 未实现 / 外部依赖</div>
</div>"""

    node_html_parts = []
    for node in nodes:
        node_id = node.get("id", "")
        title = node.get("title_zh", node_id)
        color = node.get("color", "external")
        stats = node.get("stats", {})
        stat_text = ", ".join(f"{k}={v}" for k, v in stats.items() if v)

        node_html_parts.append(f"""\
<div class="node {_color_class(node)}" data-node-id="{node_id}">
  <div class="node-header">
    <span class="node-title">{title} <code style="font-size:.75rem;color:var(--color-muted)">{node_id}</code></span>
    <span class="badge {_badge_class(color)}">{color.upper()}</span>
  </div>
  <div class="node-stats">{stat_text}</div>
  <div class="analysis">
<!-- AGENT_DESC: {node_id} -->
    <span class="analysis-placeholder">[Agent fills in natural-language analysis for {title}]</span>
<!-- /AGENT_DESC -->
  </div>
</div>""")

    return f"""\
<div class="card">
  <h2>内核设计树</h2>
  {legend}
  {''.join(node_html_parts)}
</div>"""


def _render_mermaid_stub(report: dict) -> str:
    return """\
<div class="card">
  <h2>架构图</h2>
  <div class="mermaid">
<!-- AGENT_MERMAID -->
    <pre>graph TD
  %% Agent: replace this with actual Mermaid diagram
  %% showing 14 subsystems with color-coded nodes
  subgraph Legend
    yellow[COPIED]:::copied
    red[MODIFIED]:::modified
    blue[NOVEL]:::novel
  end
  classDef copied fill:#f9a825,color:#fff
  classDef modified fill:#c62828,color:#fff
  classDef novel fill:#1565c0,color:#fff</pre>
<!-- /AGENT_MERMAID -->
  </div>
</div>"""


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
                        taxonomy: dict | None = None) -> dict:
    """Aggregate computed data into a structured report payload.

    This is the bridge between raw tool outputs and the HTML template.
    The Agent calls this to prepare data, then passes the result to render_html().
    """
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

    # Build tree nodes with color inference from compare_result
    if taxonomy and compare_result:
        by_file = compare_result.get("by_file", {})
        # Infer per-node color from function status distribution
        # (Agent can override after calling this)
        for node_id in taxonomy.get("order", []):
            stats = {"copied": 0, "disguise": 0, "modified": 0, "novel": 0}
            # Simple: mark all nodes as external by default
            # Agent fills in actual analysis
            color = "external"
            report["tree_nodes"].append({
                "id": node_id,
                "title_zh": taxonomy.get("roots", {}).get(
                    node_id.split(".")[0], {}
                ).get("title_zh", node_id) if "." not in node_id else "",
                "color": color,
                "stats": stats,
            })

    return report


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/report.py <report_data.json> [output_dir]")
        print()
        print("  report_data.json — structured report payload")
        print("  output_dir       — where to write index.html (default: stdout)")
        sys.exit(1)

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
