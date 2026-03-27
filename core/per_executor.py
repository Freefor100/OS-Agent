from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.messages import AIMessage, ToolMessage

from core.per_types import DraftDocument, EvidenceItem, ParagraphRecord


PATH_RE = re.compile(
    r"([A-Za-z0-9_./\\-]+\.(?:rs|c|h|cpp|cc|go|zig|S|s|toml|ld|md|py))(?::(\d+(?:-\d+)?))?"
)


def extract_final_stage_text(messages: List[Any], minimum_length: int = 120) -> str:
    ai_contents: List[str] = []
    for message in messages:
        if isinstance(message, AIMessage):
            content = (message.content or "").strip()
            if content and len(content) >= 20:
                ai_contents.append(content)
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = (message.content or "").strip()
            tool_calls = getattr(message, "tool_calls", None) or []
            if content and not tool_calls and len(content) >= minimum_length:
                return content
    if not ai_contents:
        return ""
    return max(ai_contents, key=len)


def _tool_to_source_type(tool_name: str) -> str:
    mapping = {
        "read_code_segment": "source_code",
        "grep_in_repo": "source_code",
        "rag_search_code": "rag_hit",
        "lsp_get_definition": "source_code",
        "lsp_get_references": "lsp_call_graph",
        "lsp_get_document_outline": "source_code",
        "lsp_get_call_graph": "lsp_call_graph",
        "get_git_history_summary": "git_history",
        "analyze_git_history": "git_history",
        "trace_file_evolution": "git_history",
        "get_commit_diff_summary": "git_history",
        "analyze_tech_stack": "readme_doc",
        "web_search": "web_background",
    }
    return mapping.get(tool_name, "source_code")


def _tool_confidence(tool_name: str, content: str) -> str:
    lowered = (content or "").lower()
    if "confidence=low" in lowered or "degraded" in lowered or "fallback" in lowered:
        return "low"
    if tool_name in {"read_code_segment", "lsp_get_definition", "lsp_get_document_outline"}:
        return "high"
    if tool_name in {"rag_search_code", "lsp_get_references", "lsp_get_call_graph"}:
        return "medium"
    if tool_name == "web_search":
        return "medium"
    return "medium"


def _extract_path_and_lines(tool_args: Dict[str, Any], content: str) -> Tuple[str, Optional[str]]:
    for key in ("file_path", "path", "repo_path"):
        value = tool_args.get(key)
        if isinstance(value, str) and "." in value and "/" in value.replace("\\", "/"):
            line_hint = None
            if "start_line" in tool_args:
                end_line = tool_args.get("end_line")
                line_hint = f"{tool_args['start_line']}-{end_line}" if end_line else str(tool_args["start_line"])
            return value.replace("\\", "/"), line_hint
    match = PATH_RE.search(content or "")
    if match:
        return match.group(1).replace("\\", "/"), match.group(2)
    return "", None


def _extract_symbol(tool_args: Dict[str, Any], content: str) -> Optional[str]:
    for key in ("symbol", "entry_function", "function_name"):
        value = tool_args.get(key)
        if value:
            return str(value)
    match = re.search(r"符号名:\s*([A-Za-z0-9_:\-]+)", content or "")
    if match:
        return match.group(1)
    return None


def extract_evidence_index(messages: List[Any]) -> List[EvidenceItem]:
    pending_tool_calls: List[Dict[str, Any]] = []
    evidence_items: List[EvidenceItem] = []
    counter = 0
    for message in messages:
        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None) or []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    pending_tool_calls.append({
                        "name": tc.get("name", "unknown"),
                        "args": tc.get("args", {}) or {},
                    })
                else:
                    pending_tool_calls.append({
                        "name": getattr(tc, "name", "unknown"),
                        "args": getattr(tc, "args", {}) or {},
                    })
        elif isinstance(message, ToolMessage):
            counter += 1
            tool_name = getattr(message, "name", None) or (pending_tool_calls[0]["name"] if pending_tool_calls else "unknown")
            tool_args = pending_tool_calls.pop(0)["args"] if pending_tool_calls else {}
            content = message.content or ""
            path, lines = _extract_path_and_lines(tool_args, content)
            symbol = _extract_symbol(tool_args, content)
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{counter:03d}",
                    path=path,
                    lines=lines,
                    symbol=symbol,
                    source_type=_tool_to_source_type(tool_name),
                    confidence=_tool_confidence(tool_name, content),
                    excerpt=(content[:500] + "...") if len(content) > 500 else content,
                    tool_name=tool_name,
                )
            )
    return evidence_items


def _path_mentions(text: str) -> List[str]:
    return [match.group(1).replace("\\", "/") for match in PATH_RE.finditer(text or "")]


def _split_paragraphs(markdown: str) -> Iterable[str]:
    raw_parts = re.split(r"\n\s*\n", markdown.strip())
    for part in raw_parts:
        text = part.strip()
        if text:
            yield text


def build_draft_document(markdown: str, evidence_index: List[EvidenceItem]) -> DraftDocument:
    heading_stack: List[str] = []
    paragraphs: List[ParagraphRecord] = []
    claim_map: Dict[str, Dict[str, Any]] = {}
    paragraph_counter = 0
    claim_counter = 0
    for block in _split_paragraphs(markdown):
        paragraph_counter += 1
        paragraph_id = f"p{paragraph_counter:03d}"
        stripped = block.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_stack = heading_stack[: max(level - 1, 0)]
            heading_stack.append(heading)
            paragraph = ParagraphRecord(paragraph_id=paragraph_id, heading_path=list(heading_stack), text=stripped)
            paragraphs.append(paragraph)
            continue

        claim_counter += 1
        claim_id = f"claim_{claim_counter:03d}"
        linked_evidence_ids: List[str] = []
        path_mentions = _path_mentions(stripped)
        lowered = stripped.lower()
        for evidence in evidence_index:
            path_tail = evidence.path.replace("\\", "/")
            symbol = (evidence.symbol or "").lower()
            if path_tail and any(path_tail.endswith(pm) or pm.endswith(path_tail) for pm in path_mentions):
                linked_evidence_ids.append(evidence.evidence_id)
            elif symbol and symbol in lowered:
                linked_evidence_ids.append(evidence.evidence_id)
            elif evidence.path and evidence.path.split("/")[-1].lower() in lowered:
                linked_evidence_ids.append(evidence.evidence_id)
        linked_evidence_ids = list(dict.fromkeys(linked_evidence_ids))
        for evidence in evidence_index:
            if evidence.evidence_id in linked_evidence_ids:
                evidence.claim_ids.append(claim_id)
                evidence.used_in_paragraphs.append(paragraph_id)
        paragraph = ParagraphRecord(
            paragraph_id=paragraph_id,
            heading_path=list(heading_stack),
            text=stripped,
            claim_ids=[claim_id],
            evidence_ids=linked_evidence_ids,
        )
        claim_map[claim_id] = {
            "paragraph_id": paragraph_id,
            "text": stripped,
            "evidence_ids": linked_evidence_ids,
        }
        paragraphs.append(paragraph)
    return DraftDocument(paragraphs=paragraphs, claim_map=claim_map)


def extract_stage_artifacts(stage_text: str, messages: Optional[List[Any]] = None) -> Dict[str, Any]:
    messages = messages or []
    evidence_index = extract_evidence_index(messages)
    draft_document = build_draft_document(stage_text, evidence_index)
    return {
        "draft_markdown": draft_document.to_markdown() or stage_text.strip(),
        "draft_document": draft_document,
        "claim_map": draft_document.claim_map,
        "evidence_index": evidence_index,
    }
