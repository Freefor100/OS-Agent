from __future__ import annotations

import json
import shutil
from pathlib import Path

from .compiler import compile_report


ROOT = Path(__file__).resolve().parents[2]
VIEWER_DIST = ROOT / "review_viewer" / "dist"


def build_report_html(case_dir: str | Path) -> Path:
    """Compile report data and publish the prebuilt React reader beside it."""
    root = Path(case_dir)
    compile_report(root)
    site_dir = root / "site"
    _copy_viewer(site_dir)
    source = site_dir / "index.html"
    report_html = site_dir / "report.html"
    shutil.copy2(source, report_html)
    return report_html


def build_index(case_dirs: list[str | Path], output: str | Path) -> Path:
    """Publish one React index and isolated report bundles for accepted cases."""
    out = Path(output)
    _copy_viewer(out)
    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for raw_dir in case_dirs:
        case_dir = Path(raw_dir)
        tags_path = case_dir / "tags.json"
        if not tags_path.exists():
            continue
        build_report_html(case_dir)
        tags = json.loads(tags_path.read_text(encoding="utf-8"))
        work_id = str(tags.get("work_id") or case_dir.name)
        dest = reports_dir / work_id
        _copy_tree(case_dir / "site", dest)
        for rel in ["tags.json", "report.md"]:
            src = case_dir / rel
            if src.exists():
                shutil.copy2(src, dest / rel)
        tags["public_paths"] = {
            "html": f"reports/{work_id}/report.html",
            "data": f"reports/{work_id}/report_data.json",
            "markdown": f"reports/{work_id}/report.md",
        }
        index.append(tags)
    (out / "site_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out / "index.html"


def _copy_viewer(destination: Path) -> None:
    if not (VIEWER_DIST / "index.html").is_file():
        raise RuntimeError(
            "React reader is not built; run `npm install` and `npm run build` in review_viewer"
        )
    destination.mkdir(parents=True, exist_ok=True)
    assets = destination / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    _copy_tree(VIEWER_DIST, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
