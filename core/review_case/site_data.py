from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from .compiler import compile_report


def build_report_html(case_dir: str | Path) -> Path:
    root = Path(case_dir)
    report_data_path = compile_report(root)
    report_data = json.loads(report_data_path.read_text(encoding="utf-8"))
    title = report_data["identity"].get("display_name", "评审报告")
    data = json.dumps(report_data, ensure_ascii=False)
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} 评审报告</title>
  <style>
    body {{ margin: 0; font-family: Inter, "Noto Sans SC", system-ui, sans-serif; background: #f5f7fa; color: #16202a; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 56px; }}
    header {{ border-bottom: 3px solid #1d4d5f; padding-bottom: 18px; margin-bottom: 24px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    h2 {{ border-top: 1px solid #d9e0e7; padding-top: 18px; margin-top: 28px; }}
    .chip {{ display: inline-flex; align-items: center; border: 1px solid #8ab4c3; color: #0f5265; padding: 1px 6px; border-radius: 4px; font-size: 12px; }}
    pre {{ white-space: pre-wrap; background: #fff; border: 1px solid #dde5ed; padding: 16px; overflow: auto; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(title)}</h1>
      <div>{html.escape(report_data["identity"].get("school", ""))} / {html.escape(report_data["identity"].get("team", ""))}</div>
    </header>
    <div id="report"></div>
  </main>
  <script type="application/json" id="report-data">{html.escape(data)}</script>
  <script>
    const data = JSON.parse(document.getElementById('report-data').textContent);
    const target = document.getElementById('report');
    target.innerHTML = data.sections.map(section => `<section><h2>${{section.title}}</h2><pre>${{section.markdown.replaceAll('&','&amp;').replaceAll('<','&lt;')}}</pre></section>`).join('');
  </script>
</body>
</html>
"""
    out = root / "site" / "report.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def build_index(case_dirs: list[str | Path], output: str | Path) -> Path:
    out = Path(output)
    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for raw_dir in case_dirs:
        case_dir = Path(raw_dir)
        tags_path = case_dir / "tags.json"
        if not tags_path.exists():
            continue
        tags = json.loads(tags_path.read_text(encoding="utf-8"))
        work_id = tags.get("work_id") or case_dir.name
        dest = reports_dir / work_id
        dest.mkdir(parents=True, exist_ok=True)
        for rel in ["site/report.html", "site/report_data.json", "evidence.jsonl", "tags.json", "report.md"]:
            src = case_dir / rel
            if src.exists():
                target = dest / Path(rel).name
                shutil.copy2(src, target)
        tags["public_paths"] = {
            "html": f"reports/{work_id}/report.html",
            "data": f"reports/{work_id}/report_data.json",
            "markdown": f"reports/{work_id}/report.md",
        }
        index.append(tags)
    (out / "site_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "index.html").write_text(_index_html(index), encoding="utf-8")
    return out / "index.html"


def _index_html(index: list[dict]) -> str:
    rows = "\n".join(
        f"<tr><td>{html.escape(item.get('display_name',''))}</td><td>{html.escape(item.get('school',''))}</td><td>{html.escape(', '.join(item.get('risk_tags', [])))}</td><td><a href='{html.escape(item.get('public_paths', {}).get('html', '#'))}'>报告</a></td></tr>"
        for item in index
    )
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OS-Agent 评审索引</title>
<style>body{{font-family:system-ui,"Noto Sans SC",sans-serif;background:#f6f8fb;color:#17212b;padding:24px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #dce3ea;padding:10px;text-align:left}}</style>
<h1>OS-Agent 评审索引</h1><table><thead><tr><th>作品</th><th>学校</th><th>风险</th><th>入口</th></tr></thead><tbody>{rows}</tbody></table></html>"""
