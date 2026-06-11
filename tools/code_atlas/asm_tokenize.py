#!/usr/bin/env python3
"""Lightweight assembly tokenizer for fingerprinting (.S/.s).

code_atlas/tree-sitter does not parse assembly. The minhash layer only needs a token
list, not an AST — so we tokenize assembly directly.

Normalization (so renamed labels / reallocated registers / changed comments still
match copied code):
  - strip comments (# // /* */)
  - registers           -> REG   (catches register reallocation)
  - label defs/refs     -> LBL   (catches renamed labels)
  - keep mnemonics & directive keywords (sd, ld, csrw, .globl, .section ...)
  - keep immediates/offsets as values (0, 8, 16 ... carry struct-layout signal)

Unit = one label block (label def to next label, the natural routine boundary in
asm). Files with no labels become one unit. Returns [(unit_name, tokens)].
"""
from __future__ import annotations

import re

# register name patterns across the arches in this corpus (RISC-V, LoongArch, ARM64).
_REG_RE = re.compile(
    r"^\$?("
    r"zero|ra|sp|gp|tp|fp|pc|lr|"                 # named (RISC-V / common)
    r"t[0-9]|t1[0-8]?|s[0-9]|s1[01]?|a[0-7]|"      # t0-t18, s0-s11, a0-a7
    r"x[0-9]|x[12][0-9]|x3[01]|"                   # x0-x31
    r"w[0-9]|w[12][0-9]|w3[01]|"                   # w0-w31 (ARM64 32-bit)
    r"r[0-9]|r1[0-9]|r2[0-9]|r3[01]|"              # r0-r31 (LoongArch / ARM)
    r"f[ats]?[0-9]+|"                              # float regs ft0/fs0/fa0/f0
    r"xzr|wzr"                                     # ARM64 zero
    r")$",
    re.IGNORECASE,
)

_NUM_RE = re.compile(r"^[-+]?(0x[0-9a-fA-F]+|[0-9]+)$")
_LABEL_DEF_RE = re.compile(r"^([A-Za-z_.$][\w.$]*):$")
_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    text = _COMMENT_BLOCK_RE.sub(" ", text)
    out = []
    for line in text.splitlines():
        for marker in ("#", "//", ";"):
            idx = line.find(marker)
            if idx != -1:
                line = line[:idx]
        out.append(line)
    return "\n".join(out)


def _tokenize_line(line: str) -> list[str]:
    """One asm line -> normalized tokens. First word = mnemonic/directive (kept)."""
    line = line.replace("(", " ( ").replace(")", " ) ").replace(",", " , ")
    words = line.split()
    if not words:
        return []
    toks: list[str] = []
    for i, w in enumerate(words):
        if i == 0:
            toks.append(w.lower())
            continue
        if w in ("(", ")", ","):
            toks.append(w)
        elif _REG_RE.match(w):
            toks.append("REG")
        elif _NUM_RE.match(w):
            toks.append(w)
        else:
            toks.append("LBL")
    return toks


def tokenize_asm(text: str) -> list[tuple[str, list[str]]]:
    """Assembly source -> [(unit_label, normalized_tokens)] per label block."""
    text = _strip_comments(text)
    units: list[tuple[str, list[str]]] = []
    cur_label = "(file)"
    cur_tokens: list[str] = []

    def flush():
        if cur_tokens:
            units.append((cur_label, list(cur_tokens)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LABEL_DEF_RE.match(line)
        if m:
            flush()
            cur_label = m.group(1)
            cur_tokens = []
            continue
        cur_tokens.extend(_tokenize_line(line))
    flush()
    return units


if __name__ == "__main__":  # quick manual check
    import sys
    for label, toks in tokenize_asm(open(sys.argv[1]).read()):
        print(f"{label}: {len(toks)} tok  {toks[:24]}")
