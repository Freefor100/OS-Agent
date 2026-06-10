#!/usr/bin/env python3
"""Corpus-wide lineage overview — the judge's bird's-eye deliverable.

Reads output/lineage_clusters.json (produced by lineage_idf.py) and renders a
single self-contained HTML: family genealogies, orphan board (originality
candidates), and same-cohort high-score edges (plagiarism review targets).

Zero compute, zero LLM — pure presentation of stage-1 results.
Output: output/_overview/index.html
"""
from __future__ import annotations

import html
import json
from pathlib import Path

SAME_YEAR_REVIEW = 0.80   # same-cohort edges at/above this -> flag for manual review
ORPHAN_MAX = 0.20         # best-containment below this -> strong originality candidate


def esc(s) -> str:
    return html.escape(str(s))


def main():
    data = json.loads(Path("output/lineage_clusters.json").read_text())
    fams = data["families"]
    year = data["year"]
    edges = data["edges"]
    orphans = data["orphans"]

    # families, largest first
    fam_rows = []
    for c in sorted(fams, key=len, reverse=True):
        chain = " → ".join(f'<span title="{esc(year.get(n,"?"))}">{esc(n)}</span>'
                            for n in c)  # already year-sorted by lineage_idf
        fam_rows.append(f'<tr><td style="text-align:center">{len(c)}</td><td>{chain}</td></tr>')

    # same-cohort review targets (potential same-year copying — no time ordering to excuse it)
    review = [e for e in edges if e["same_year"] and e["score"] >= SAME_YEAR_REVIEW]
    rev_rows = "\n".join(
        f'<tr><td style="text-align:right">{e["score"]:.2f}</td>'
        f'<td><code>{esc(e["a"])}</code></td><td><code>{esc(e["b"])}</code></td>'
        f'<td>{esc(year.get(e["a"],"?"))}</td></tr>'
        for e in review
    )

    # directed lineage (older <- newer), top by score
    directed = [e for e in edges if not e["same_year"]][:30]
    dir_rows = "\n".join(
        f'<tr><td style="text-align:right">{e["score"]:.2f}</td>'
        f'<td><code>{esc(e["newer"])}</code> <small>({esc(year.get(e["newer"],"?"))})</small></td>'
        f'<td>← 派生自 ←</td>'
        f'<td><code>{esc(e["older"])}</code> <small>({esc(year.get(e["older"],"?"))})</small></td></tr>'
        for e in directed
    )

    # orphans
    orph_rows = "\n".join(
        f'<tr><td><code>{esc(o["repo"])}</code></td>'
        f'<td style="text-align:right">{o["best"]:.2f}</td>'
        f'<td>{esc(o["year"])}</td>'
        f'<td>{"★ 强原创候选" if o["best"] < ORPHAN_MAX else ""}</td></tr>'
        for o in orphans
    )

    n_singleton = sum(1 for v in data["peers"].values() if not v)
    html_doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>全库查重总览</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:23px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{padding:5px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}
code{{font-size:12px}} .note{{color:#888;font-size:13px}} .warn{{color:#c62828}}
</style></head><body>
<h1>全库血缘 / 查重总览</h1>
<p class="note">{len(year)} 个作品 · {len(fams)} 个跨届家族 · {n_singleton} 个独立作品 ·
方向由届号判定(老 ← 新);同届高分边无时间先后可循,需人工复审。</p>

<h2 class="warn">⚠ 同届复审重点（同年 + 双向 containment ≥ {SAME_YEAR_REVIEW}）</h2>
<p class="note">同届作品高度相似，无「先后」可解释，是最该人工核查的互抄候选。</p>
<table><tr><th>相似度</th><th>作品 A</th><th>作品 B</th><th>届</th></tr>{rev_rows}</table>

<h2>跨届派生关系（老 ← 新，top 30）</h2>
<table><tr><th>相似度</th><th>新作品</th><th></th><th>来源</th></tr>{dir_rows}</table>

<h2>血缘家族（{len(fams)} 个，按规模）</h2>
<table><tr><th>成员数</th><th>谱系链（按届号）</th></tr>{"".join(fam_rows)}</table>

<h2>孤儿榜（原创候选）</h2>
<p class="note">best = 该作品代码在全库任何其他作品中的最高占比；越低越独立。</p>
<table><tr><th>作品</th><th>best</th><th>届</th><th></th></tr>{orph_rows}</table>
</body></html>"""

    out_dir = Path("output/_overview")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html_doc, encoding="utf-8")
    print(f"overview -> {out}")
    print(f"  families={len(fams)} review_targets={len(review)} orphans={len(orphans)}")


if __name__ == "__main__":
    main()
