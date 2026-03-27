from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage

from core.per_executor import extract_final_stage_text, extract_stage_artifacts
from core.per_types import DraftDocument, EvidenceItem, ParagraphRecord, StageState


def _find_paragraph(draft_document: DraftDocument, paragraph_id: str):
    for paragraph in draft_document.paragraphs:
        if paragraph.paragraph_id == paragraph_id:
            return paragraph
    return None


def collect_targeted_evidence(
    agent: Any,
    state: StageState,
    base_messages: Sequence[Any],
    action: Dict[str, Any],
    recursion_limit: int = 18,
) -> Tuple[List[EvidenceItem], List[Any]]:
    target_claim = action.get("target_claim_id", "")
    target_para = action.get("target_paragraph_id", "")
    hint = action.get("hint", "")
    paragraph = _find_paragraph(state.draft_document, target_para) if state.draft_document and target_para else None
    target_text = paragraph.text if paragraph else state.draft_markdown[:400]
    prompt = HumanMessage(content=f"""你现在只做定向补证，不要重写整章报告。

目标阶段：{state.stage_title}
目标段落：{target_para or '未指定'}
目标 claim：{target_claim or '未指定'}
修补提示：{hint}

当前相关文本：
{target_text}

只围绕这段内容补充最必要的源码证据。优先使用：
1. `rag_search_code`
2. `lsp_get_definition` / `lsp_get_call_graph`
3. `read_code_segment`

不要重新探索整个仓库，也不要生成完整章节报告。若无法找到源码实现，请明确说明“未发现实现”。
""")
    final_state = None
    safe_messages = list(base_messages)
    while safe_messages and isinstance(safe_messages[-1], AIMessage) and getattr(safe_messages[-1], "tool_calls", None):
        safe_messages.pop()
    followup_inputs = {"messages": safe_messages + [prompt]}
    for event in agent.stream(followup_inputs, config={"recursion_limit": recursion_limit}):
        for _, current_state in event.items():
            final_state = current_state
    messages = final_state.get("messages", []) if final_state else []
    artifacts = extract_stage_artifacts(extract_final_stage_text(messages, minimum_length=60), messages)
    return artifacts["evidence_index"], messages


def rewrite_single_paragraph(
    llm: Any,
    stage_title: str,
    paragraph_text: str,
    evidence_patch: Sequence[EvidenceItem],
    action: Dict[str, Any],
) -> str:
    evidence_lines = []
    for item in evidence_patch[:5]:
        citation = item.path
        if item.lines:
            citation = f"{citation}:{item.lines}" if citation else item.lines
        evidence_lines.append(
            f"- {citation or '未定位路径'} | symbol={item.symbol or '-'} | source={item.source_type} | confidence={item.confidence}"
        )
    prompt = f"""你是技术报告修订器，只重写一个段落，不要输出额外解释。

阶段标题：{stage_title}
修补动作：{action.get('action_type')}
修补提示：{action.get('hint', '')}

原段落：
{paragraph_text}

新证据：
{chr(10).join(evidence_lines) if evidence_lines else '- 未新增证据'}

要求：
1. 保留原段落主体信息与语气。
2. 如果证据不足，不要强行断言已实现；应降级为“未发现实现”或“文档提及但未见代码”。
3. 若有源码路径，尽量在段落中加入反引号路径引用。
4. 只输出修订后的单段正文。
"""
    response = llm.invoke(prompt)
    return (getattr(response, "content", "") or paragraph_text).strip()


def _replace_paragraph_text(draft_document: DraftDocument, paragraph_id: str, new_text: str) -> List[str]:
    changed: List[str] = []
    for paragraph in draft_document.paragraphs:
        if paragraph.paragraph_id == paragraph_id:
            paragraph.text = new_text.strip()
            changed.append(paragraph_id)
    return changed


def _drop_claim_text(draft_document: DraftDocument, paragraph_id: str) -> List[str]:
    changed: List[str] = []
    for paragraph in draft_document.paragraphs:
        if paragraph.paragraph_id == paragraph_id:
            paragraph.text = "未发现足够源码证据支撑此前结论，现降级为“文档提及但未见明确代码实现”。"
            changed.append(paragraph_id)
    return changed


def _append_paragraph(
    draft_document: DraftDocument,
    new_text: str,
    evidence_patch: Sequence[EvidenceItem],
) -> List[str]:
    next_idx = len(draft_document.paragraphs) + 1
    paragraph_id = f"p{next_idx:03d}"
    claim_id = f"claim_{len(draft_document.claim_map) + 1:03d}"
    record = ParagraphRecord(
        paragraph_id=paragraph_id,
        heading_path=[],
        text=new_text.strip(),
        claim_ids=[claim_id],
        evidence_ids=[item.evidence_id for item in evidence_patch],
    )
    draft_document.paragraphs.append(record)
    draft_document.claim_map[claim_id] = {
        "paragraph_id": paragraph_id,
        "text": record.text,
        "evidence_ids": record.evidence_ids,
    }
    for item in evidence_patch:
        item.claim_ids.append(claim_id)
        item.used_in_paragraphs.append(paragraph_id)
    return [paragraph_id]


def repair_stage(
    state: StageState,
    agent: Any,
    llm: Any,
    base_messages: Sequence[Any],
    recursion_limit: int = 18,
) -> List[str]:
    if not state.review_result or not state.draft_document:
        return []

    touched_paragraph_ids: List[str] = []
    for action in state.review_result.repair_actions[:8]:
        action_type = action.get("action_type")
        paragraph_id = action.get("target_paragraph_id")
        evidence_patch: List[EvidenceItem] = []

        if action_type in {"add_evidence", "append_missing_module"}:
            evidence_patch, _ = collect_targeted_evidence(
                agent=agent,
                state=state,
                base_messages=base_messages,
                action=action,
                recursion_limit=recursion_limit,
            )
            if evidence_patch:
                state.evidence_index.extend(evidence_patch)
                state.evidence_index = list({item.evidence_id + item.path + (item.symbol or ""): item for item in state.evidence_index}.values())

        if action_type in {"rewrite_paragraph", "append_missing_module", "normalize_terminology"} and paragraph_id:
            paragraph = _find_paragraph(state.draft_document, paragraph_id)
            if not paragraph:
                continue
            new_text = rewrite_single_paragraph(
                llm=llm,
                stage_title=state.stage_title,
                paragraph_text=paragraph.text,
                evidence_patch=evidence_patch or [item for item in state.evidence_index if paragraph_id in item.used_in_paragraphs],
                action=action,
            )
            touched_paragraph_ids.extend(_replace_paragraph_text(state.draft_document, paragraph_id, new_text))
            state.repair_history.append({
                "action": action,
                "paragraph_id": paragraph_id,
                "evidence_count": len(evidence_patch),
            })
        elif action_type == "drop_unsupported_claim" and paragraph_id:
            touched_paragraph_ids.extend(_drop_claim_text(state.draft_document, paragraph_id))
            state.repair_history.append({"action": action, "paragraph_id": paragraph_id})
        elif action_type == "append_missing_module" and not paragraph_id:
            new_text = rewrite_single_paragraph(
                llm=llm,
                stage_title=state.stage_title,
                paragraph_text="请新增一个简洁段落，补充当前阶段缺失的关键问题回答。",
                evidence_patch=evidence_patch,
                action=action,
            )
            touched_paragraph_ids.extend(_append_paragraph(state.draft_document, new_text, evidence_patch))
            state.repair_history.append({
                "action": action,
                "paragraph_id": touched_paragraph_ids[-1] if touched_paragraph_ids else "",
                "evidence_count": len(evidence_patch),
            })

    state.draft_markdown = state.draft_document.to_markdown()
    state.status = "patched"
    return list(dict.fromkeys(touched_paragraph_ids))
