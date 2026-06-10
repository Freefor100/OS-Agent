#!/usr/bin/env python3
"""Stage-4 report assembly — turns deterministic provenance into a judge-facing
HTML report. Zero LLM (the stage-3 LLM narrative is an optional injected file).

Reuses scripts/provenance.py classification. Produces:
  * contribution table: EXTERNAL / FRAMEWORK / PEER / ORIGINAL / TRIVIAL %
  * per-directory provenance mix (the structural fingerprint)
  * ORIGINAL function list (the student's real work, with file:line)
  * declaration cross-check slot (filled from an optional JSON)

Output: output/<target>/_report/index.html  (self-contained, no JS deps)
"""
from __future__ import annotations

import html
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.provenance import (fingerprints, functions_and_edges, classify_provenance,
                                 top_dir, PEER_TOKEN_FLOOR)
from scripts.exclude import load_rules as load_exclude_rules, apply_exclude
from core.kernel_tree import ROOT_NODES_V2, EXTRA_NODE_SPECS, node_title_zh, ANALYSIS_ORDER_V2

COLORS = {
    "ORIGINAL": "#2e7d32",          # green — student's own
    "PORTED-FRAMEWORK": "#f9a825",  # amber — framework base
    "PORTED-PEER": "#c62828",       # red — shared with peers (review)
    "EXTERNAL": "#9e9e9e",          # grey — third-party deps
    "TRIVIAL": "#cfd8dc",           # pale — no discriminative signal
}
LABEL = {
    "ORIGINAL": "自研",
    "PORTED-FRAMEWORK": "框架底座",
    "PORTED-PEER": "同源/共享",
    "EXTERNAL": "外部依赖",
    "TRIVIAL": "样板(无判别力)",
}


def bar(pct: float, color: str) -> str:
    return (f'<div style="background:#eee;border-radius:3px;height:18px;width:100%">'
            f'<div style="background:{color};height:18px;border-radius:3px;'
            f'width:{pct:.1f}%"></div></div>')


def esc(s) -> str:
    return html.escape(str(s))


# module = first two path segments (e.g. os/src, api/src/imp) collapsed to a
# readable label; good enough to group functions into architecture boxes.
def module_of(path: str) -> str:
    parts = [p for p in path.split("/") if p not in ("", ".", "src")]
    if not parts:
        return "root"
    if parts[0] in ("os", "kernel", "api", "core") and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def mermaid_arch(fns_by_id: dict, edges, fp_class: dict) -> str:
    """Module-level call graph, each module colored by dominant provenance.

    fns_by_id: fn_id -> meta(with file,sz,fp); edges: [(src,dst)];
    fp_class: fn meta -> class name. Returns a Mermaid flowchart string.
    """
    from collections import defaultdict
    mod_class_sz = defaultdict(lambda: defaultdict(int))   # module -> class -> tok
    fn_mod = {}
    for fid, f in fns_by_id.items():
        if f["file"].startswith("vendor/"):
            continue
        m = module_of(f["file"])
        fn_mod[fid] = m
        mod_class_sz[m][fp_class[fid]] += f["sz"]

    # module edges (dedup, drop self-loops), weight = call count
    medges = defaultdict(int)
    for s, d in edges:
        ms, md = fn_mod.get(s), fn_mod.get(d)
        if ms and md and ms != md:
            medges[(ms, md)] += 1

    # keep the biggest modules so the graph stays readable
    top_mods = sorted(mod_class_sz, key=lambda m: -sum(mod_class_sz[m].values()))[:14]
    keep = set(top_mods)

    color = {"ORIGINAL": "#2e7d32", "PORTED-FRAMEWORK": "#f9a825",
             "PORTED-PEER": "#c62828", "EXTERNAL": "#9e9e9e", "TRIVIAL": "#cfd8dc"}
    lines = ["flowchart LR"]
    nid = {m: f"m{i}" for i, m in enumerate(top_mods)}
    for m in top_mods:
        dom = max(mod_class_sz[m], key=lambda c: mod_class_sz[m][c])
        sz = sum(mod_class_sz[m].values())
        lines.append(f'  {nid[m]}["{esc(m)}<br/>{sz}tok"]')
        lines.append(f'  style {nid[m]} fill:{color[dom]},color:#fff,stroke:#333')
    drawn = 0
    for (ms, md), w in sorted(medges.items(), key=lambda kv: -kv[1]):
        if ms in keep and md in keep and drawn < 40:
            lines.append(f'  {nid[ms]} --> {nid[md]}')
            drawn += 1
    return "\n".join(lines)


def tree_section(classes: dict) -> str:
    """Kernel design tree (14 subsystems, 112 leaf nodes) with provenance coloring."""
    LABEL_DOM = {"ORIGINAL": "自研", "PORTED-FRAMEWORK": "框架底座",
                 "PORTED-PEER": "移植/共享", "EXTERNAL": "外部依赖",
                 "TRIVIAL": "样板"}
    COLOR = {"ORIGINAL": "#2e7d32", "PORTED-FRAMEWORK": "#f9a825",
             "PORTED-PEER": "#c62828", "EXTERNAL": "#9e9e9e", "TRIVIAL": "#cfd8dc"}

    # index all functions by name, with their provenance class
    fn_prov: dict[str, list[str]] = {}
    for cname, fns in classes.items():
        prov_label = LABEL_DOM.get(cname, cname)
        for f in fns:
            fn_prov.setdefault(f["name"].lower(), []).append(prov_label)

    def node_provenance(node_id: str) -> dict:
        specs = EXTRA_NODE_SPECS.get(node_id, {})
        symbols = [s.lower() for s in specs.get("symbols", [])]
        prov_counts: dict[str, int] = defaultdict(int)
        matched_names: list[str] = []
        for s in symbols:
            if s in fn_prov:
                matched_names.append(s)
                for prov in fn_prov[s]:
                    prov_counts[prov] += 1
        if not prov_counts:
            return {"status": "unimplemented", "color": "#cfd8dc", "label": "未实现",
                    "fns": ""}
        dom = max(prov_counts, key=prov_counts.get)
        return {"status": "implemented", "color": COLOR.get(dom, "#cfd8dc"),
                "label": dom, "fns": ", ".join(matched_names[:4])}

    rows = []
    for root, children in ROOT_NODES_V2.items():
        rp = node_provenance(root)
        rows.append(f'<tr style="font-weight:600;background:#f5f5f5">'
                    f'<td colspan="3">{esc(node_title_zh(root))} ({root})</td>'
                    f'<td><span style="display:inline-block;width:10px;height:10px;'
                    f'background:{rp["color"]};border-radius:2px"></span></td></tr>')
        for child in children:
            child_id = f"{root}.{child}"
            cp = node_provenance(child_id)
            rows.append(f'<tr><td></td><td>{esc(node_title_zh(child_id))} '
                        f'<span style="font-size:11px;color:#888">({child})</span></td>'
                        f'<td style="font-size:11px">{esc(cp["fns"]) or "—"}</td>'
                        f'<td><span style="display:inline-block;width:10px;height:10px;'
                        f'background:{cp["color"]};border-radius:2px" '
                        f'title="{cp["label"]}"></span> {cp["label"]}</td></tr>')
    return (f'<h2>内核设计树</h2>'
            f'<p class="note">14 子系统 × 三色出身标注。🟩自研 🟨框架底座 🟥移植/共享 '
            f'⬜外部 ▫️未实现。函数名来自 NODE_SPECS 符号匹配,非 xv6 系内核可能匹配不全。</p>'
            f'<table><tr><th>子系统</th><th>节点</th><th>关键函数</th><th>出身</th></tr>'
            f'{"".join(rows)}</table>')


def build_html(target: str, framework: str, classes: dict, xcheck: dict | None,
               arch: str = "", declared: dict | None = None) -> str:
    order = ["ORIGINAL", "PORTED-FRAMEWORK", "PORTED-PEER", "EXTERNAL", "TRIVIAL"]
    tot_sz = sum(f["sz"] for fns in classes.values() for f in fns) or 1
    tot_n = sum(len(fns) for fns in classes.values()) or 1

    # contribution table
    rows = []
    for c in order:
        n = len(classes[c])
        sz = sum(f["sz"] for f in classes[c])
        rows.append(
            f'<tr><td><span style="display:inline-block;width:12px;height:12px;'
            f'background:{COLORS[c]};border-radius:2px"></span> {LABEL[c]}</td>'
            f'<td style="text-align:right">{n}</td>'
            f'<td style="text-align:right">{100*n/tot_n:.0f}%</td>'
            f'<td style="text-align:right">{sz}</td>'
            f'<td style="width:200px">{bar(100*sz/tot_sz, COLORS[c])}</td>'
            f'<td style="text-align:right">{100*sz/tot_sz:.0f}%</td></tr>'
        )
    contrib = "\n".join(rows)

    # per-dir mix (token-weighted; excludes all vendored/third-party dirs so
    # GNU bash / dependency don't dominate the student's own structure)
    dirstat = defaultdict(lambda: defaultdict(int))
    for c, fns in classes.items():
        for f in fns:
            if f["file"].startswith("vendor/"):
                continue
            dirstat[top_dir(f["file"])][c] += f["sz"]
    dir_rows = []
    for d, st in sorted(dirstat.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(st.values()) or 1
        seg = "".join(
            f'<div style="background:{COLORS[c]};height:16px;width:{100*st[c]/tot:.1f}%" '
            f'title="{LABEL[c]} {100*st[c]/tot:.0f}%"></div>'
            for c in order if st[c]
        )
        dir_rows.append(
            f'<tr><td><code>{esc(d)}</code></td><td style="text-align:right">{tot}tok</td>'
            f'<td style="width:320px"><div style="display:flex;border-radius:3px;overflow:hidden">{seg}</div></td></tr>'
        )
    dir_mix = "\n".join(dir_rows)

    # ORIGINAL list — the student's real work
    orig = sorted(classes["ORIGINAL"], key=lambda x: -x["sz"])[:40]
    orig_rows = "\n".join(
        f'<tr><td><code>{esc(f["name"])}</code></td><td><code>{esc(f["file"])}:{f["line"]}</code></td>'
        f'<td style="text-align:right">{f["sz"]}</td></tr>'
        for f in orig
    )

    # declaration cross-check (optional, from stage-3)
    if xcheck:
        xrows = "\n".join(
            f'<tr><td>{esc(r.get("claim",""))}</td><td>{esc(r.get("fact",""))}</td>'
            f'<td>{esc(r.get("verdict",""))}</td></tr>'
            for r in xcheck.get("rows", [])
        )
        xsection = (f'<h2>声明-事实交叉核查</h2><table><tr><th>选手声明</th>'
                    f'<th>指纹事实</th><th>判定</th></tr>{xrows}</table>')
    else:
        xsection = ('<h2>声明-事实交叉核查</h2><p class="note">未提供 LLM 核查判定 '
                    '(stage-3 读 README 散文血缘 + 比对指纹后生成 xcheck.json 注入)。</p>')

    # declared dependencies/lineage (deterministic extraction, stage-3a)
    decl_section = ""
    if declared:
        def declist(items, label):
            if not items:
                return ""
            lis = "".join(f"<li><code>{esc(x)}</code></li>" for x in items[:20])
            return f'<p class="note">{label}</p><ul style="font-size:12px;margin:4px 0">{lis}</ul>'
        decl_section = (
            '<h2>自报依赖与血缘（确定性提取）</h2>'
            '<p class="note">来自 Cargo.toml / .gitmodules / README 的结构化引用。'
            '散文血缘声明（如「基于 xv6-loongson」无 URL）需 LLM 补读，不在此列。</p>'
            + declist(declared.get("git_deps"), "git 依赖（owner/repo）")
            + declist(declared.get("submodules"), "git submodule（第三方）")
            + declist(declared.get("readme_refs"), "README github 引用（自报血缘）")
            + declist(declared.get("crates"), "crates.io 依赖")
        )

    realwork = sum(f["sz"] for f in classes["ORIGINAL"]) + sum(f["sz"] for f in classes["PORTED-PEER"])
    arch_section = ""
    if arch:
        arch_section = (
            '<h2>模块架构图（按出身染色）</h2>'
            '<p class="note">每个模块按主导出身染色：🟩自研 🟨框架底座 🟥同源/共享 ⬜外部 ▫️样板；'
            'vendored 第三方目录已排除。箭头为模块间调用。</p>'
            f'<pre class="mermaid">\n{arch}\n</pre>'
        )
    mermaid_js = ('<script type="module">'
                  'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";'
                  'mermaid.initialize({startOnLoad:true});</script>') if arch else ""
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>查重报告 · {esc(target)}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#222}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{padding:5px 8px;border-bottom:1px solid #eee;text-align:left}}
code{{font-size:12px}} .note{{color:#888;font-size:13px}} .meta{{color:#666;font-size:13px}}
.mermaid{{background:#fafafa;border:1px solid #eee;border-radius:4px;padding:8px}}
</style>{mermaid_js}</head><body>
<h1>内核查重报告</h1>
<p class="meta">作品: <code>{esc(target)}</code> &nbsp; 框架基准: <code>{esc(framework)}</code>
&nbsp; PEER 下限: {PEER_TOKEN_FLOOR}tok</p>
<h2>贡献占比</h2>
<table><tr><th>来源</th><th>函数数</th><th>占比</th><th>token</th><th>token 占比</th><th></th></tr>
{contrib}</table>
<p class="note">「自研 + 同源/共享」中真正属于选手的工作量(token)≈ {realwork}。
框架底座/外部依赖不计入选手贡献;样板函数无判别力,单列。</p>
{arch_section}
{tree_section(classes)}
<h2>各目录来源构成</h2>
<table><tr><th>目录</th><th>规模</th><th>构成</th></tr>{dir_mix}</table>
{decl_section}
{xsection}
<h2>选手自研函数 (ORIGINAL,按规模 top 40)</h2>
<p class="note">这是 stage-3 LLM 重点阅读、向评委展示「真实工作」的清单,每条带 file:line 证据。</p>
<table><tr><th>函数</th><th>位置</th><th>token</th></tr>{orig_rows}</table>
</body></html>"""


def main():
    target = sys.argv[1]
    # framework baseline is OPTIONAL: macrokernels (xv6/npucore family) have no
    # component framework — pass "none". Then PORTED-FRAMEWORK is empty and an
    # earlier same-family member acts as the base via PORTED-PEER. See DESIGN.md §4.
    framework = sys.argv[2] if len(sys.argv) > 2 else "none"
    peers = sys.argv[3:]
    has_fw = framework not in ("none", "-", "")

    # peers come from the CLI (run.py passes search.py results).
    # framework baseline name is excluded to avoid miscounting framework code as PEER.
    fw_name = Path(framework).name.replace("_baseline_", "").replace("oscomp-", "") if has_fw else ""
    if has_fw:
        # drop any peer that is the framework baseline (e.g. 'arceos' upstream)
        peers = [p for p in peers if p not in (fw_name, "arceos", Path(framework).name)]

    tfns, edges = functions_and_edges(f"repos/{target}")
    fw = fingerprints(framework) if has_fw else set()
    peer_fps = set()
    for p in peers:
        peer_fps |= fingerprints(f"repos/{p}")
    classes = classify_provenance(tfns, fw, peer_fps,
                                   exclude_rules=load_exclude_rules(target))

    # per-fn_id class map for the architecture graph (code units only; asm has no fn_id/edges)
    fp_class = {}
    fns_by_id = {f["fn_id"]: f for f in tfns if f.get("fn_id")}
    for cname, fns in classes.items():
        for f in fns:
            if f.get("fn_id"):
                fp_class[f["fn_id"]] = cname
    arch = mermaid_arch(fns_by_id, edges, fp_class)

    xpath = Path(f"/tmp/xcheck_{target}.json")
    xcheck = json.loads(xpath.read_text()) if xpath.exists() else None
    dpath = Path(f"/tmp/declared_{target}.json")
    declared = json.loads(dpath.read_text()) if dpath.exists() else None

    out_dir = Path(f"output/{target}/_report")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    fw_label = framework if has_fw else "(无框架基准·宏内核范式)"
    out.write_text(build_html(target, fw_label, classes, xcheck, arch, declared), encoding="utf-8")
    print(f"report -> {out}")
    for c in ("ORIGINAL", "PORTED-FRAMEWORK", "PORTED-PEER", "EXTERNAL", "TRIVIAL"):
        print(f"  {c:18s}: {len(classes[c])}")


if __name__ == "__main__":
    main()
