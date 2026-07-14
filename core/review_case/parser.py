from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVIDENCE_REF_RE = re.compile(r"\[@(E\d{3,})\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+/)+(?:[\w.-]+)(?:\.[A-Za-z0-9_+-]+)?")
SYSCALL_RE = re.compile(r"\b(?:sys_[A-Za-z0-9_]+|SYS_[A-Za-z0-9_]+)\b")
CONFIG_RE = re.compile(r"\b(?:CONFIG_[A-Za-z0-9_]+|[A-Za-z0-9_-]+=(?:y|n|[A-Za-z0-9_./-]+))\b")


@dataclass
class Heading:
    level: int
    title: str
    start_line: int
    end_line: int
    body: str


@dataclass
class MarkdownDocument:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    headings: list[Heading] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    code_anchors: list[str] = field(default_factory=list)
    text: str = ""

    def section(self, title: str) -> str:
        for heading in self.headings:
            if heading.title == title:
                return heading.body.strip()
        return ""

    def has_heading(self, title: str) -> bool:
        return any(heading.title == title for heading in self.headings)


def parse_markdown(path: str | Path) -> MarkdownDocument:
    md_path = Path(path)
    text = md_path.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            raw_fm = text[4:end].strip()
            body = text[text.find("\n", end + 1) + 1 :]
            loaded = yaml.safe_load(raw_fm) if raw_fm else {}
            frontmatter = loaded if isinstance(loaded, dict) else {}
    headings = _parse_headings(body)
    refs = EVIDENCE_REF_RE.findall(body)
    anchors = extract_code_anchors(body)
    return MarkdownDocument(path=md_path, frontmatter=frontmatter, body=body, headings=headings, evidence_refs=refs, code_anchors=anchors, text=text)


def _parse_headings(body: str) -> list[Heading]:
    lines = body.splitlines()
    heads: list[tuple[int, str, int]] = []
    for idx, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line)
        if match:
            heads.append((len(match.group(1)), match.group(2).strip(), idx))
    headings: list[Heading] = []
    for index, (level, title, start) in enumerate(heads):
        end = heads[index + 1][2] - 1 if index + 1 < len(heads) else len(lines)
        heading_body = "\n".join(lines[start:end])
        headings.append(Heading(level=level, title=title, start_line=start, end_line=end, body=heading_body))
    return headings


def extract_code_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for match in INLINE_CODE_RE.finditer(text):
        token = match.group(1).strip()
        if _looks_like_anchor(token):
            anchors.append(token)
    for pattern in (PATH_RE, SYSCALL_RE, CONFIG_RE):
        anchors.extend(match.group(0).strip() for match in pattern.finditer(text))
    deduped: list[str] = []
    seen = set()
    for anchor in anchors:
        if anchor not in seen:
            deduped.append(anchor)
            seen.add(anchor)
    return deduped


def _looks_like_anchor(token: str) -> bool:
    return (
        "/" in token
        or token.startswith(("sys_", "SYS_", "CONFIG_"))
        or bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*\(\)?$", token))
        or bool(re.match(r"^[A-Z][A-Za-z0-9_]{2,}$", token))
        or token.endswith((".rs", ".c", ".h", ".S", ".cpp", ".toml", ".ld", ".mk"))
    )


def split_h2_sections(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    positions: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            positions.append((match.group(1).strip(), idx))
    sections = []
    for index, (title, start) in enumerate(positions):
        end = positions[index + 1][1] if index + 1 < len(positions) else len(lines)
        sections.append({"id": slugify(title), "title": title, "markdown": "\n".join(lines[start:end]).strip()})
    return sections


def slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff-]+", "", text)
    return text or "section"
