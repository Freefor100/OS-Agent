"""Backfill the current glossary into already-generated judge_view.json files.

Re-runs the same glossary_lookup the pipeline uses at finalize time, so existing
demo outputs show the filled concept definitions without a full LLM re-run.
Maturity is an LLM judgment and is left untouched (defaults stay).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.kernel_glossary import glossary_lookup, load_kernel_glossary
from core.kernel_tree import EXTRA_NODE_SPECS, apply_kernel_taxonomy

ROOT = Path(__file__).resolve().parent.parent
concepts = json.loads((ROOT / "core" / "kernel_concepts.json").read_text(encoding="utf-8"))
vocab = json.loads((ROOT / "core" / "kernel_mechanism_vocab.json").read_text(encoding="utf-8"))
_, vocab, _ = apply_kernel_taxonomy(concepts, vocab, dict(EXTRA_NODE_SPECS))
glossary = load_kernel_glossary(vocab)

for d in sys.argv[1:]:
    p = Path(d) / "judge_view.json"
    if not p.is_file():
        print("skip (no judge_view):", d)
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    used = {}
    ok = 0
    for claim in data.get("claims", {}).values():
        g = glossary_lookup(glossary, claim.get("canonical_tag", ""), claim.get("node_id"))
        claim["glossary"] = g
        if g.get("status") == "ok":
            ok += 1
            used[g["full_tag"]] = g
    data["claim_glossary"] = used
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{d}: {ok}/{len(data.get('claims', {}))} claims now have ok glossary")
