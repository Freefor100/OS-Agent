"""HTML report renderer for OS-Agent-D.

Renders the final report as multi-page HTML:
- index.html: header info + chapter 01 overview + chapter 10 history + nav buttons
- 02.html ~ 09.html: rendered directly from _per_stage/xx_answers.json (no markdown intermediate)
"""
from __future__ import annotations

import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple


CHAPTER_COLORS: Dict[str, str] = {
    "02": "#e74c3c",
    "03": "#2ecc71",
    "04": "#3498db",
    "05": "#9b59b6",
    "06": "#1abc9c",
    "07": "#e67e22",
    "08": "#5b2c6f",
    "09": "#34495e",
}

CHAPTER_TITLES: Dict[str, str] = {
    "02": "启动架构与 Trap/系统调用",
    "03": "内存管理（物理/虚拟/分配器）",
    "04": "进程/线程/调度与多核",
    "05": "文件系统与设备 I/O",
    "06": "同步互斥与进程间通信",
    "07": "安全机制与权限模型",
    "08": "网络子系统与协议栈",
    "09": "调试机制与错误处理",
}

_EV_PATTERN = re.compile(r"(ev_[a-f0-9_]{6,})")
_EV_PAREN_PATTERN = re.compile(r"[（(](ev_[a-f0-9_]{6,})[)）]")

def _base_css() -> str:
    return """
:root {
    --bg: #f8f9fa;
    --card-bg: #ffffff;
    --text: #2c3e50;
    --text-muted: #6c757d;
    --border: #dee2e6;
    --code-bg: #f1f3f5;
    --link: #2980b9;
    --accent: #3498db;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.7;
    padding: 0;
}
.container { max-width: 1100px; margin: 0 auto; padding: 2rem 1.5rem; }
h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
h2 { font-size: 1.5rem; margin: 2rem 0 0.8rem; padding-bottom: 0.4rem; border-bottom: 2px solid var(--border); }
h3 { font-size: 1.25rem; margin: 1.5rem 0 0.6rem; color: var(--text); }
h4 { font-size: 1.1rem; margin: 1.2rem 0 0.4rem; }
p { margin: 0.6rem 0; }
ul, ol { margin: 0.6rem 0 0.6rem 1.5rem; }
li { margin: 0.3rem 0; }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
    background: var(--code-bg);
    padding: 0.15em 0.4em;
    border-radius: 3px;
    font-size: 0.88em;
    font-family: "JetBrains Mono", "Fira Code", Consolas, monospace;
}
pre {
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 1rem 1.2rem;
    border-radius: 8px;
    overflow-x: auto;
    margin: 1rem 0;
    font-size: 0.85rem;
    line-height: 1.5;
}
pre code { background: none; padding: 0; color: inherit; }
blockquote {
    border-left: 4px solid var(--accent);
    padding: 0.5rem 1rem;
    margin: 1rem 0;
    background: #eef6fc;
    border-radius: 0 6px 6px 0;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 1rem 0;
    font-size: 0.9rem;
    overflow-x: auto;
    display: block;
}
thead { background: #f1f3f5; }
th, td {
    padding: 0.6rem 0.8rem;
    border: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
}
tr:nth-child(even) { background: #f8f9fa; }
tr:hover { background: #e9ecef; }
.evidence-link {
    display: inline-block;
    background: #fff3cd;
    color: #856404;
    padding: 0.1em 0.5em;
    border-radius: 12px;
    font-size: 0.78em;
    font-family: monospace;
    cursor: pointer;
    border: 1px solid #ffc107;
    transition: all 0.2s;
}
.evidence-link:hover {
    background: #ffc107;
    color: #1a1a1a;
    text-decoration: none;
    transform: scale(1.05);
}
.evidence-anchor {
    display: inline-block;
    background: #d4edda;
    color: #155724;
    padding: 0.1em 0.5em;
    border-radius: 12px;
    font-size: 0.78em;
    font-family: monospace;
    border: 1px solid #28a745;
    scroll-margin-top: 80px;
}
.evidence-anchor:target {
    background: #ffc107;
    color: #1a1a1a;
    box-shadow: 0 0 0 3px rgba(255, 193, 7, 0.4);
    animation: pulse 0.6s ease-out;
}
@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.1); }
    100% { transform: scale(1); }
}
hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }

/* --- PLACEHOLDER_NAV --- */
"""


def _nav_css() -> str:
    return """
.top-nav {
    position: sticky;
    top: 0;
    background: rgba(255,255,255,0.95);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border);
    padding: 0.7rem 1.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    z-index: 100;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.top-nav a {
    padding: 0.3rem 0.8rem;
    border-radius: 6px;
    font-size: 0.9rem;
    transition: background 0.2s;
}
.top-nav a:hover { background: #e9ecef; text-decoration: none; }
.top-nav .spacer { flex: 1; }
.nav-cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 1rem;
    margin: 2rem 0;
}
.nav-card {
    display: block;
    padding: 1.2rem 1rem;
    border-radius: 12px;
    color: #fff;
    font-weight: 600;
    font-size: 1rem;
    text-align: center;
    transition: transform 0.2s, box-shadow 0.2s;
    text-decoration: none;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}
.nav-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.18);
    text-decoration: none;
}
.nav-card .chapter-num {
    display: block;
    font-size: 0.75rem;
    opacity: 0.85;
    margin-bottom: 0.3rem;
}
.header-info {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 1.5rem 2rem;
    margin-bottom: 2rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    border: 1px solid var(--border);
}
.header-info h1 { color: var(--accent); }
.header-info .meta-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 0.5rem 2rem;
    margin-top: 1rem;
}
.header-info .meta-item { font-size: 0.92rem; }
.header-info .meta-label { color: var(--text-muted); font-weight: 500; }
.chapter-badge {
    display: inline-block;
    padding: 0.3rem 1rem;
    border-radius: 20px;
    color: #fff;
    font-weight: 600;
    font-size: 0.85rem;
    margin-bottom: 1rem;
}
"""

def _process_evidence_links(text: str) -> str:
    """Convert evidence ID references to clickable anchor links."""
    first_occurrences: set = set()

    def _replace_paren(m: re.Match) -> str:
        ev_id = m.group(1)
        return f'<a href="#{ev_id}" class="evidence-link">{ev_id}</a>'

    def _replace_bare(m: re.Match) -> str:
        ev_id = m.group(1)
        if ev_id not in first_occurrences:
            first_occurrences.add(ev_id)
            return f'<span id="{ev_id}" class="evidence-anchor">{ev_id}</span>'
        return f'<a href="#{ev_id}" class="evidence-link">{ev_id}</a>'

    text = _EV_PAREN_PATTERN.sub(_replace_paren, text)
    text = _EV_PATTERN.sub(_replace_bare, text)
    return text


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def md_to_html(md_text: str) -> str:
    """Convert markdown text to HTML with evidence link processing.

    Handles: headings, code blocks, inline code, tables, lists, blockquotes,
    bold, italic, links, horizontal rules, and evidence IDs.
    """
    lines = md_text.split("\n")
    out: List[str] = []
    i = 0
    in_table = False
    in_list = False
    list_type = ""

    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines: List[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(_escape(lines[i]))
                i += 1
            i += 1
            code_html = "\n".join(code_lines)
            out.append(f'<pre><code class="language-{lang}">{code_html}</code></pre>')
            continue

        if line.startswith("|") and "|" in line[1:]:
            if not in_table:
                in_table = True
                out.append("<table>")
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr></thead>")
                i += 1
                if i < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i]):
                    i += 1
                out.append("<tbody>")
                continue
            else:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
                continue
        elif in_table:
            in_table = False
            out.append("</tbody></table>")

        if re.match(r"^#{1,6}\s", line):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            anchor = re.sub(r"[^\w一-鿿]+", "-", text).strip("-").lower()
            out.append(f'<h{level} id="{anchor}">{_inline(text)}</h{level}>')
            i += 1
            continue

        if line.startswith("> "):
            bq_lines = []
            while i < len(lines) and lines[i].startswith("> "):
                bq_lines.append(lines[i][2:])
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(bq_lines))}</blockquote>")
            continue

        if re.match(r"^[-*]\s", line):
            if not in_list or list_type != "ul":
                if in_list:
                    out.append(f"</{list_type}>")
                in_list = True
                list_type = "ul"
                out.append("<ul>")
            out.append(f"<li>{_inline(line[2:].strip())}</li>")
            i += 1
            continue
        elif re.match(r"^\d+\.\s", line):
            if not in_list or list_type != "ol":
                if in_list:
                    out.append(f"</{list_type}>")
                in_list = True
                list_type = "ol"
                out.append("<ol>")
            text = re.sub(r"^\d+\.\s*", "", line)
            out.append(f"<li>{_inline(text.strip())}</li>")
            i += 1
            continue
        elif in_list:
            in_list = False
            out.append(f"</{list_type}>")

        if re.match(r"^---+$", line.strip()):
            out.append("<hr>")
            i += 1
            continue

        if line.strip() == "":
            i += 1
            continue

        out.append(f"<p>{_inline(line)}</p>")
        i += 1

    if in_table:
        out.append("</tbody></table>")
    if in_list:
        out.append(f"</{list_type}>")

    result = "\n".join(out)
    result = _process_evidence_links(result)
    return result


def _inline(text: str) -> str:
    """Process inline markdown: bold, italic, code, links, images."""
    text = re.sub(r"`([^`]+)`", r'<code>\1</code>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" style="max-width:100%">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


# ---------------------------------------------------------------------------
# Direct JSON → HTML rendering for stages 02-09
# ---------------------------------------------------------------------------

_VALUE_BADGE: Dict[str, Tuple[str, str, str]] = {
    "yes_strong": ("✅ 强支撑", "#d4edda", "#155724"),
    "yes_weak": ("⚠️ 弱支撑", "#fff3cd", "#856404"),
    "no": ("❌ 未实现", "#f8d7da", "#721c24"),
    "unknown": ("❓ 未知", "#e2e3e5", "#383d41"),
    "implemented": ("✅ 已实现", "#d4edda", "#155724"),
    "stub": ("⚠️ 存根", "#fff3cd", "#856404"),
    "not_found": ("❌ 未发现", "#f8d7da", "#721c24"),
}

_TRI_STATE_ZH: Dict[str, str] = {
    "implemented": "已实现",
    "stub": "桩实现",
    "not_found": "未发现",
    "unknown": "证据不足/未知",
}


def _value_badge_html(value: Any) -> str:
    """Render a value as a colored badge."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    badge = _VALUE_BADGE.get(text)
    if badge:
        label, bg, fg = badge
        return f'<span style="display:inline-block;padding:0.15em 0.6em;border-radius:12px;background:{bg};color:{fg};font-size:0.85em;font-weight:500">{label}</span>'
    return f"<span>{_escape(text)}</span>"


def _render_fact_table_html(fact_answers: List[Dict[str, Any]], desc_map: Dict[str, str]) -> str:
    """Render fact_answers as an HTML table with colored badges."""
    if not fact_answers:
        return ""
    rows: List[str] = []
    rows.append('<table class="fact-table">')
    rows.append("<thead><tr><th>子问题</th><th>考核项</th><th>结论</th><th>备注</th></tr></thead>")
    rows.append("<tbody>")
    for item in fact_answers:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("fact_id") or "").strip()
        fkey = str(item.get("fact_key") or "").strip()
        name = fkey or fid
        desc = desc_map.get(fid, "-")
        value = item.get("value")
        notes = str(item.get("notes") or "").strip().replace("\n", " ")
        ev_ids = item.get("used_evidence_ids") or []

        notes_html = _escape(notes)
        for eid in ev_ids:
            if isinstance(eid, str) and eid.startswith("ev_"):
                notes_html += f' <a href="#{eid}" class="evidence-link">{eid}</a>'

        rows.append(
            f"<tr><td><strong>{_escape(name)}</strong></td>"
            f"<td>{_escape(desc)}</td>"
            f"<td>{_value_badge_html(value)}</td>"
            f"<td>{notes_html}</td></tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)


def _render_answer_value_html(value: Any, question_type: str = "") -> str:
    """Render the main answer value."""
    if isinstance(value, str):
        s = value.strip()
        if question_type == "tri_state_impl" and s in _TRI_STATE_ZH:
            return f'<div class="answer-value">{_value_badge_html(s)} <span style="color:var(--text-muted);margin-left:0.5em">{_TRI_STATE_ZH[s]}</span></div>'
        if s in _VALUE_BADGE:
            return f'<div class="answer-value">{_value_badge_html(s)}</div>'
        return f'<div class="answer-value"><p>{_process_evidence_links(_escape(s))}</p></div>'
    if isinstance(value, dict) or isinstance(value, list):
        formatted = json.dumps(value, ensure_ascii=False, indent=2)
        return f'<div class="answer-value"><pre><code>{_escape(formatted)}</code></pre></div>'
    return f'<div class="answer-value">{_escape(str(value))}</div>'


def render_answers_to_html(payload: Dict[str, Any], stage_qa: Optional[Dict[str, Any]] = None) -> str:
    """Render answers JSON payload directly to HTML content (no markdown intermediate).

    This is the primary renderer for stages 02-09.
    """
    answers = payload.get("answers", [])

    fact_desc_map: Dict[str, Dict[str, str]] = {}
    if stage_qa and isinstance(stage_qa.get("questions"), list):
        for q in stage_qa["questions"]:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or "").strip()
            fact_desc_map[qid] = {}
            for sf in q.get("structured_facts", []) if isinstance(q.get("structured_facts"), list) else []:
                if not isinstance(sf, dict):
                    continue
                fid = str(sf.get("fact_id") or "").strip()
                fdesc = str(sf.get("question") or "").strip()
                if fid and fdesc:
                    fact_desc_map[qid][fid] = fdesc

    parts: List[str] = []
    for a in (answers if isinstance(answers, list) else []):
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id", "")).strip()
        stem = str(a.get("stem", "")).strip()
        qtype = str(a.get("question_type", "")).strip()
        value = a.get("value")
        notes = (a.get("notes") or "").strip() if isinstance(a.get("notes"), str) else ""
        fact_answers = a.get("fact_answers") or []
        ev_ids = a.get("used_evidence_ids") or []

        heading = f"{qid} {stem}" if stem else qid
        anchor = re.sub(r"[^\w]+", "-", qid).strip("-").lower()
        parts.append(f'<section class="question-block" id="{anchor}">')
        parts.append(f'<h3>{_escape(heading)}</h3>')

        # 先展示最终结论
        parts.append(_render_answer_value_html(value, qtype))

        if notes:
            notes_html = _process_evidence_links(_escape(notes))
            parts.append(f'<div class="answer-notes">{notes_html}</div>')

        # 子事实表格折叠
        if isinstance(fact_answers, list) and fact_answers:
            parts.append('<details class="fact-details">')
            parts.append(f'<summary>子事实明细（{len(fact_answers)} 项）</summary>')
            parts.append(_render_fact_table_html(fact_answers, fact_desc_map.get(qid, {})))
            parts.append('</details>')

        for eid in ev_ids:
            if isinstance(eid, str) and eid.startswith("ev_"):
                parts.append(f'<span id="{eid}" class="evidence-anchor">{eid}</span> ')

        parts.append("</section>")

    return "\n".join(parts)


def _answers_html_extra_css() -> str:
    return """
.question-block {
    margin: 1.5rem 0;
    padding: 1.2rem 1.5rem;
    background: var(--card-bg);
    border-radius: 10px;
    border: 1px solid var(--border);
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.question-block h3 {
    margin: 0 0 0.8rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid var(--border);
}
.fact-table {
    width: 100%;
    font-size: 0.88rem;
    display: table;
}
.fact-table th { background: #f1f3f5; font-weight: 600; }
.fact-table td, .fact-table th { padding: 0.5rem 0.7rem; }
.conclusion-label {
    margin: 0.8rem 0 0.3rem;
    font-weight: 600;
    color: var(--text-muted);
    font-size: 0.9rem;
}
.answer-value {
    margin: 0.4rem 0;
    padding: 0.4rem 0;
}
.answer-notes {
    margin-top: 0.5rem;
    padding: 0.6rem 1rem;
    background: #f8f9fa;
    border-radius: 6px;
    font-size: 0.9rem;
    color: var(--text-muted);
    line-height: 1.6;
}
.fact-details {
    margin-top: 0.8rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
}
.fact-details summary {
    padding: 0.5rem 1rem;
    background: #f1f3f5;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 500;
    color: var(--text-muted);
    user-select: none;
    list-style: none;
}
.fact-details summary::-webkit-details-marker { display: none; }
.fact-details summary::before {
    content: "▶ ";
    font-size: 0.75em;
    transition: transform 0.2s;
    display: inline-block;
}
.fact-details[open] summary::before { content: "▼ "; }
.fact-details summary:hover { background: #e9ecef; color: var(--text); }
.fact-details .fact-table { margin: 0; border-radius: 0; }
.fact-details .fact-table th,
.fact-details .fact-table td { border-left: none; border-right: none; }
.fact-details .fact-table tr:last-child td { border-bottom: none; }
"""



def _html_head(title: str, extra_css: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
<style>
{_base_css()}
{_nav_css()}
{extra_css}
</style>
</head>
<body>
"""


def render_index_html(
    *,
    repo_name: str,
    repo_url: str,
    analysis_date: str,
    total_quality: Optional[int],
    overview_md: str,
    history_md: str,
    callgraph_svg: Optional[str] = None,
    chapters: List[Tuple[str, str]],
    repo_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the index.html homepage.

    Args:
        chapters: list of (stage_num, title) for nav cards
        repo_meta: optional dict with keys: year, competition, sub_competition, school, team
    """
    meta = repo_meta or {}
    parts: List[str] = []
    parts.append(_html_head(f"{repo_name} - OS技术分析报告"))
    parts.append('<div class="container">')

    parts.append('<div class="header-info">')
    parts.append(f"<h1>{_escape(repo_name)} 操作系统技术分析报告</h1>")
    parts.append('<div class="meta-grid">')
    if meta.get("year"):
        parts.append(f'<div class="meta-item"><span class="meta-label">年份：</span>{_escape(str(meta["year"]))}</div>')
    if meta.get("competition"):
        parts.append(f'<div class="meta-item"><span class="meta-label">赛事：</span>{_escape(meta["competition"])}</div>')
    if meta.get("sub_competition"):
        parts.append(f'<div class="meta-item"><span class="meta-label">子赛事：</span>{_escape(meta["sub_competition"])}</div>')
    if meta.get("school"):
        parts.append(f'<div class="meta-item"><span class="meta-label">学校：</span>{_escape(meta["school"])}</div>')
    if meta.get("team"):
        parts.append(f'<div class="meta-item"><span class="meta-label">队伍名称：</span>{_escape(meta["team"])}</div>')
    parts.append(f'<div class="meta-item"><span class="meta-label">仓库地址：</span><a href="{_escape(repo_url)}">{_escape(repo_url)}</a></div>')
    parts.append(f'<div class="meta-item"><span class="meta-label">分析日期：</span>{_escape(analysis_date)}</div>')
    parts.append(f'<div class="meta-item"><span class="meta-label">分析工具：</span>OS-Agent-D Multi-Agent</div>')
    if total_quality is not None:
        parts.append(f'<div class="meta-item"><span class="meta-label">报告质量：</span><strong>{total_quality}/100</strong></div>')
    parts.append("</div></div>")

    parts.append("<h2>章节导航</h2>")
    parts.append('<div class="nav-cards">')
    for num, title in chapters:
        color = CHAPTER_COLORS.get(num, "#34495e")
        parts.append(
            f'<a href="html/{num}.html" class="nav-card" style="background:{color}">'
            f'<span class="chapter-num">第 {num} 章</span>{_escape(title)}</a>'
        )
    parts.append("</div>")

    if callgraph_svg:
        parts.append("<h2>Call Graph 概览</h2>")
        parts.append(f'<div style="overflow-x:auto;margin:1rem 0">{callgraph_svg}</div>')

    parts.append("<h2>项目概览与技术栈</h2>")
    parts.append(md_to_html(overview_md))

    parts.append("<h2>开发历史与里程碑</h2>")
    parts.append(md_to_html(history_md))

    parts.append('<footer style="margin-top:3rem;padding:1.5rem 0;border-top:1px solid var(--border);color:var(--text-muted);font-size:0.85rem;text-align:center">')
    parts.append("本报告由 OS-Agent-D Multi-Agent 自动生成</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_chapter_html(
    *,
    stage_num: str,
    title: str,
    content_md: str = "",
    content_html: str = "",
    prev_chapter: Optional[Tuple[str, str]] = None,
    next_chapter: Optional[Tuple[str, str]] = None,
    repo_name: str = "",
) -> str:
    """Render a single chapter page (02~09).

    Provide either content_md (will be converted) or content_html (used directly).
    """
    color = CHAPTER_COLORS.get(stage_num, "#34495e")
    extra_css = f".chapter-accent {{ color: {color}; }}\n" + _answers_html_extra_css()
    parts: List[str] = []
    parts.append(_html_head(f"第{stage_num}章 {title} - {repo_name}", extra_css))

    parts.append('<nav class="top-nav">')
    parts.append('<a href="../index.html">← 首页</a>')
    if prev_chapter:
        parts.append(f'<a href="{prev_chapter[0]}.html">← {_escape(prev_chapter[1][:8])}</a>')
    parts.append('<span class="spacer"></span>')
    parts.append(f'<strong class="chapter-accent">第 {stage_num} 章</strong>')
    parts.append('<span class="spacer"></span>')
    if next_chapter:
        parts.append(f'<a href="{next_chapter[0]}.html">{_escape(next_chapter[1][:8])} →</a>')
    parts.append("</nav>")

    parts.append('<div class="container">')
    parts.append(f'<span class="chapter-badge" style="background:{color}">第 {stage_num} 章</span>')
    parts.append(f"<h1>{_escape(title)}</h1>")
    parts.append("<hr>")

    if content_html:
        parts.append(content_html)
    else:
        parts.append(md_to_html(content_md))

    parts.append('<div style="margin-top:3rem;display:flex;justify-content:space-between;flex-wrap:wrap;gap:1rem">')
    if prev_chapter:
        parts.append(f'<a href="{prev_chapter[0]}.html" style="padding:0.6rem 1.2rem;background:{CHAPTER_COLORS.get(prev_chapter[0],"#34495e")};color:#fff;border-radius:8px;text-decoration:none">← {_escape(prev_chapter[1])}</a>')
    else:
        parts.append("<span></span>")
    parts.append('<a href="../index.html" style="padding:0.6rem 1.2rem;background:#6c757d;color:#fff;border-radius:8px;text-decoration:none">首页</a>')
    if next_chapter:
        parts.append(f'<a href="{next_chapter[0]}.html" style="padding:0.6rem 1.2rem;background:{CHAPTER_COLORS.get(next_chapter[0],"#34495e")};color:#fff;border-radius:8px;text-decoration:none">{_escape(next_chapter[1])} →</a>')
    else:
        parts.append("<span></span>")
    parts.append("</div>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


def _load_stage_qa_safe(stage_id: str) -> Optional[Dict[str, Any]]:
    """Try to load stage QA definition; return None on failure."""
    try:
        from core.describe_stage_qa import load_stage_qa
        return load_stage_qa(stage_id)
    except Exception:
        return None


_STAGE_ID_MAP: Dict[str, str] = {
    "02": "02_boot_trap",
    "03": "03_mem_mgmt",
    "04": "04_process_smp",
    "05": "05_fs_drivers",
    "06": "06_sync_ipc",
    "07": "07_security",
    "08": "08_network",
    "09": "09_debug_error",
}


def publish_html_report(
    *,
    repo_output_dir: str,
    repo_name: str,
    repo_url: str,
    analysis_date: str,
    total_quality: Optional[int] = None,
    repo_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Main entry point: generate HTML report pages.

    Output layout:
      - repo_output_dir/index.html  (homepage)
      - repo_output_dir/html/02.html ~ 09.html  (chapter pages)

    repo_meta: optional dict with keys year/competition/sub_competition/school/team.
    If not provided, tries to read from repo_output_dir/repo_profile.json.

    Returns the path to index.html.
    """
    sections_dir = os.path.join(repo_output_dir, "sections")
    per_stage_dir = os.path.join(repo_output_dir, "_per_stage")

    if repo_meta is None:
        profile_path = os.path.join(repo_output_dir, "repo_profile.json")
        if os.path.isfile(profile_path):
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                repo_meta = {
                    k: profile.get(k)
                    for k in ("year", "competition", "sub_competition", "school", "team")
                    if profile.get(k)
                }
            except Exception:
                repo_meta = {}
    html_dir = os.path.join(repo_output_dir, "html")
    os.makedirs(html_dir, exist_ok=True)

    overview_md = ""
    history_md = ""

    if os.path.isdir(sections_dir):
        for fname in sorted(os.listdir(sections_dir)):
            if not fname.endswith(".md"):
                continue
            base = os.path.splitext(fname)[0]
            if base.startswith("01_"):
                with open(os.path.join(sections_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                    overview_md = f.read().strip()
            elif base.startswith("10_") or "开发历史" in base or "history" in base.lower():
                with open(os.path.join(sections_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                    history_md = f.read().strip()

    chapter_data: List[Tuple[str, str, str]] = []

    for num in ("02", "03", "04", "05", "06", "07", "08", "09"):
        stage_id = _STAGE_ID_MAP[num]
        title = CHAPTER_TITLES.get(num, stage_id)
        content_html = ""

        answers_path = os.path.join(per_stage_dir, f"{stage_id}_answers.json") if os.path.isdir(per_stage_dir) else ""
        if answers_path and os.path.isfile(answers_path):
            try:
                with open(answers_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                stage_qa = _load_stage_qa_safe(stage_id)
                content_html = render_answers_to_html(payload, stage_qa)
            except Exception:
                content_html = ""

        if not content_html and os.path.isdir(sections_dir):
            for fname in sorted(os.listdir(sections_dir)):
                base = os.path.splitext(fname)[0]
                if base.startswith(f"{num}_"):
                    with open(os.path.join(sections_dir, fname), "r", encoding="utf-8", errors="ignore") as f:
                        content_html = md_to_html(f.read().strip())
                    break

        if content_html:
            chapter_data.append((num, title, content_html))

    chapters_for_nav = [(num, title) for num, title, _ in chapter_data]

    callgraph_svg = None
    svg_path = os.path.join(repo_output_dir, "callgraph_overview.svg")
    if os.path.isfile(svg_path):
        with open(svg_path, "r", encoding="utf-8", errors="ignore") as f:
            callgraph_svg = f.read()

    index_html = render_index_html(
        repo_name=repo_name,
        repo_url=repo_url,
        analysis_date=analysis_date,
        total_quality=total_quality,
        repo_meta=repo_meta,
        overview_md=overview_md,
        history_md=history_md,
        callgraph_svg=callgraph_svg,
        chapters=chapters_for_nav,
    )
    index_path = os.path.join(repo_output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    for idx, (num, title, content_html) in enumerate(chapter_data):
        prev_ch = (chapter_data[idx - 1][0], chapter_data[idx - 1][1]) if idx > 0 else None
        next_ch = (chapter_data[idx + 1][0], chapter_data[idx + 1][1]) if idx < len(chapter_data) - 1 else None
        page_html = render_chapter_html(
            stage_num=num,
            title=title,
            content_html=content_html,
            prev_chapter=prev_ch,
            next_chapter=next_ch,
            repo_name=repo_name,
        )
        chapter_path = os.path.join(html_dir, f"{num}.html")
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(page_html)

    return index_path
