from __future__ import annotations

import difflib
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from core.per_executor import extract_final_stage_text, extract_stage_artifacts
from core.per_llm_stages import extract_json_object
from core.per_io_preview import log_llm_response_tokens, print_agent_long_preview
from core.per_types import DraftDocument, EvidenceItem, ParagraphRecord, StageState

logger = logging.getLogger(__name__)

# ReAct 每轮约消耗 2～3 个 graph step；18 极易在补证时触顶。
DEFAULT_REPAIR_RECURSION_LIMIT = 64

# ⑤ 段落修补：优先 JSON 有序子串替换（失败再整段重写）
MAX_DIFF_EDITS = 5
MIN_PARA_CHARS_FOR_DIFF = 48
MAX_PARA_CHARS_FOR_DIFF = 14000


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
    recursion_limit: int = DEFAULT_REPAIR_RECURSION_LIMIT,
    on_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    log_io: bool = True,
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
    if log_io:
        print(
            f"   📤 ⑤ 补证子任务: 段落={target_para or '—'} | hint={hint[:160]}{'…' if len(hint) > 160 else ''}"
        )
        print(f"      · 追加 HumanMessage ≈{len(prompt.content or '')} 字符（定向补证，非整章重写）")
    final_state = None
    safe_messages = list(base_messages)
    while safe_messages and isinstance(safe_messages[-1], AIMessage) and getattr(safe_messages[-1], "tool_calls", None):
        safe_messages.pop()
    followup_inputs = {"messages": safe_messages + [prompt]}
    try:
        for event in agent.stream(followup_inputs, config={"recursion_limit": recursion_limit}):
            for node_name, current_state in event.items():
                final_state = current_state
                if on_stream_step is not None:
                    on_stream_step(node_name, current_state)
    except GraphRecursionError:
        logger.warning(
            "collect_targeted_evidence 已达 recursion_limit=%s，使用已收集消息继续抽取证据",
            recursion_limit,
        )
    messages = final_state.get("messages", []) if final_state else []
    artifacts = extract_stage_artifacts(extract_final_stage_text(messages, minimum_length=60), messages)
    evs = artifacts["evidence_index"]
    if log_io:
        print(f"   📥 ⑤ 补证完成: 抽取证据条目 {len(evs)} 条")
        for i, it in enumerate(evs[:5], 1):
            print(f"      {i}. {it.path or '?'} | {it.symbol or '-'} | {it.source_type}")
        if len(evs) > 5:
            print(f"      … 另有 {len(evs) - 5} 条")
    return evs, messages


def _format_evidence_lines(evidence_patch: Sequence[EvidenceItem], limit: int = 5) -> List[str]:
    lines: List[str] = []
    for item in evidence_patch[:limit]:
        citation = item.path
        if item.lines:
            citation = f"{citation}:{item.lines}" if citation else item.lines
        lines.append(
            f"- {citation or '未定位路径'} | symbol={item.symbol or '-'} | source={item.source_type} | confidence={item.confidence}"
        )
    return lines


def _apply_ordered_string_edits(
    paragraph_text: str, edits: List[Dict[str, str]]
) -> Tuple[Optional[str], str]:
    """按顺序做子串替换；每条 old_string 须在**当前**正文中恰好出现 1 次。"""
    t = paragraph_text
    for i, ed in enumerate(edits):
        old_s = ed.get("old_string")
        new_s = ed.get("new_string", "")
        if old_s is None or not isinstance(old_s, str):
            return None, f"edit[{i}] 缺少 old_string"
        if not isinstance(new_s, str):
            return None, f"edit[{i}] new_string 类型错误"
        if old_s == "":
            return None, f"edit[{i}] old_string 为空"
        n = t.count(old_s)
        if n == 0:
            return None, f"edit[{i}] old_string 未找到"
        if n > 1:
            return None, f"edit[{i}] old_string 出现 {n} 次（需唯一）"
        t = t.replace(old_s, new_s, 1)
    return t, ""


def _parse_diff_edits_from_response(content: str) -> Optional[List[Dict[str, str]]]:
    data = extract_json_object(content or "")
    if not data or not isinstance(data.get("edits"), list):
        return None
    out: List[Dict[str, str]] = []
    for item in data["edits"][:MAX_DIFF_EDITS]:
        if not isinstance(item, dict):
            continue
        o = item.get("old_string")
        n = item.get("new_string", "")
        if not isinstance(o, str) or not isinstance(n, str):
            continue
        if o == "":
            continue
        out.append({"old_string": o, "new_string": n})
    return out


def _try_diff_patch_via_llm(
    llm: Any,
    *,
    stage_title: str,
    paragraph_text: str,
    evidence_lines: List[str],
    action: Dict[str, Any],
    paragraph_id: str,
    log_io: bool,
) -> Optional[str]:
    """让模型输出有序 old_string/new_string 补丁；应用成功则返回新正文，否则 None。"""
    ev_block = "\n".join(evidence_lines) if evidence_lines else "- 未新增证据"
    prompt = f"""你是技术编辑，只能用「精确子串替换」修订下面这一段正文，以**最小改动**满足修补意图。

阶段标题：{stage_title}
修补动作：{action.get('action_type')}
修补提示：{action.get('hint', '')}

原段落（下文 JSON 里每条 old_string 必须从这段正文中**逐字复制**，包括换行与空格）：
---
{paragraph_text}
---

新证据摘要：
{ev_block}

输出**仅一段** ```json```，格式严格如下：
{{"edits":[{{"old_string":"从原文复制的连续子串","new_string":"替换为"}}]}}

规则：
1. 按数组顺序依次替换：第 k 条的 old_string 必须在**执行完前 k-1 条替换之后**的正文中出现**恰好一次**。
2. 优先 1～4 条小补丁；不要无故替换大段无关文字。
3. 至多 {MAX_DIFF_EDITS} 条。
4. 若无法用安全补丁完成，输出 {{"edits":[]}}（系统将自动改为整段重写）。"""

    if log_io:
        print(
            f"   📤 ⑤ 精细 diff 补丁 LLM: {paragraph_id or '?'} | 原文 {len(paragraph_text):,} 字符 | "
            f"动作={action.get('action_type')}"
        )
    try:
        response = llm.invoke(prompt)
        raw = (getattr(response, "content", None) or "").strip()
    except Exception as e:
        logger.warning("_try_diff_patch_via_llm invoke 失败: %s", e)
        if log_io:
            print(f"   ⚠️ ⑤ diff 补丁: invoke 失败 — {e}，将整段改写")
        return None

    if log_io:
        log_llm_response_tokens("⑤ 精细 diff 补丁", response)
        print_agent_long_preview(
            f"【⑤ Patch】 diff 模型原始回复 ({paragraph_id}) Agent:",
            raw,
            max_chars=4000,
            max_lines=80,
        )

    edits = _parse_diff_edits_from_response(raw)
    if not edits:
        if log_io:
            print("   ⚠️ ⑤ diff 补丁: 无有效 edits[]，将整段改写")
        return None

    applied, err = _apply_ordered_string_edits(paragraph_text, edits)
    if applied is None:
        if log_io:
            print(f"   ⚠️ ⑤ diff 补丁应用失败: {err}，将整段改写")
        return None

    if applied == paragraph_text:
        if log_io:
            print("   ⚠️ ⑤ diff 补丁应用后与原文相同，将整段改写")
        return None

    if log_io:
        print(f"   ✅ ⑤ 已应用 {len(edits)} 条子串替换（精细 diff）")
        old_lines = paragraph_text.splitlines()
        new_lines = applied.splitlines()
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"{paragraph_id or 'para'}/before",
                tofile=f"{paragraph_id or 'para'}/after",
                lineterm="",
                n=3,
            )
        )
        if diff_lines:
            diff_body = "\n".join(diff_lines[:80])
            if len(diff_lines) > 80:
                diff_body += f"\n…（diff 共 {len(diff_lines)} 行，仅展示前 80 行）"
            print_agent_long_preview(
                "【⑤ Patch】 应用补丁后 unified diff Agent:",
                diff_body,
                max_chars=8000,
                max_lines=85,
            )
    return applied.strip()


def rewrite_single_paragraph(
    llm: Any,
    stage_title: str,
    paragraph_text: str,
    evidence_patch: Sequence[EvidenceItem],
    action: Dict[str, Any],
    *,
    paragraph_id: str = "",
    log_io: bool = True,
    prefer_diff_edits: bool = True,
) -> str:
    evidence_lines = _format_evidence_lines(evidence_patch)
    body = (paragraph_text or "").strip()
    if (
        prefer_diff_edits
        and paragraph_id != "(新段落)"
        and MIN_PARA_CHARS_FOR_DIFF <= len(body) <= MAX_PARA_CHARS_FOR_DIFF
    ):
        diff_text = _try_diff_patch_via_llm(
            llm,
            stage_title=stage_title,
            paragraph_text=paragraph_text,
            evidence_lines=evidence_lines,
            action=action,
            paragraph_id=paragraph_id,
            log_io=log_io,
        )
        if diff_text is not None:
            return diff_text

    prompt = f"""你是技术报告修订器，只重写一个段落，不要输出额外解释。

阶段标题：{stage_title}
修补动作：{action.get('action_type')}
修补提示：{action.get('hint', '')}

原段落：
{paragraph_text}

新证据：
{chr(10).join(evidence_lines) if evidence_lines else "- 未新增证据"}

要求：
1. 保留原段落主体信息与语气。
2. 如果证据不足，不要强行断言已实现；应降级为“未发现实现”或“文档提及但未见代码”。
3. 若有源码路径，尽量在段落中加入反引号路径引用。
4. 只输出修订后的单段正文。
"""
    old = paragraph_text or ""
    ol = old.count("\n") + (1 if old else 0)
    if log_io:
        print(
            f"   📤 ⑤ 段落改写 LLM: {paragraph_id or '?'} | 原文 {len(old):,} 字符 / {ol} 行 | "
            f"动作={action.get('action_type')}"
        )
        print_agent_long_preview(
            f"【⑤ Patch】 改写前原文预览 ({paragraph_id}) Agent:",
            old,
            max_chars=3500,
            max_lines=80,
        )
    response = llm.invoke(prompt)
    new_text = (getattr(response, "content", "") or paragraph_text).strip()
    if log_io:
        log_llm_response_tokens("⑤ 段落改写", response)
        nl = new_text.count("\n") + (1 if new_text else 0)
        print(
            f"   📥 ⑤ 改写后: {len(new_text):,} 字符 / {nl} 行（与原文行差 {nl - ol:+d}）"
        )
        print_agent_long_preview(
            f"【⑤ Patch】 改写后正文预览 ({paragraph_id}) Agent:",
            new_text,
            max_chars=3500,
            max_lines=80,
        )
        old_lines = (paragraph_text or "").splitlines()
        new_lines = new_text.splitlines()
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"{paragraph_id or 'para'}/before",
                tofile=f"{paragraph_id or 'para'}/after",
                lineterm="",
                n=2,
            )
        )
        if diff_lines:
            diff_body = "\n".join(diff_lines[:60])
            if len(diff_lines) > 60:
                diff_body += f"\n…（diff 共 {len(diff_lines)} 行，仅展示前 60 行）"
            print_agent_long_preview(
                "【⑤ Patch】 unified diff（行级变更） Agent:",
                diff_body,
                max_chars=8000,
                max_lines=70,
            )
        else:
            print("   （unified_diff 无差异行：可能与原文相同或仅空白变化）")
    return new_text


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
    recursion_limit: int = DEFAULT_REPAIR_RECURSION_LIMIT,
    repair_actions_override: Optional[List[Dict[str, Any]]] = None,
    on_stream_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    repair_verbose: bool = True,
) -> List[str]:
    if not state.review_result or not state.draft_document:
        return []

    queue = repair_actions_override if repair_actions_override is not None else state.review_result.repair_actions
    touched_paragraph_ids: List[str] = []
    if repair_verbose:
        print(
            f"\n   📋 ⑤ Apply 队列: 共 {min(len(queue), 8)} 步（override={'是' if repair_actions_override else '否'}）"
        )

    for i, action in enumerate(queue[:8], 1):
        action_type = action.get("action_type")
        paragraph_id = action.get("target_paragraph_id")
        evidence_patch: List[EvidenceItem] = []
        if repair_verbose:
            print(
                f"\n   ▶ ⑤ Apply 步骤 {i}/{min(len(queue), 8)}: action={action_type} "
                f"para={paragraph_id or '—'} hint={(action.get('hint') or '')[:100]}"
            )

        if action_type in {"add_evidence", "append_missing_module"}:
            evidence_patch, _ = collect_targeted_evidence(
                agent=agent,
                state=state,
                base_messages=base_messages,
                action=action,
                recursion_limit=recursion_limit,
                on_stream_step=on_stream_step,
                log_io=repair_verbose,
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
                paragraph_id=paragraph_id,
                log_io=repair_verbose,
            )
            touched_paragraph_ids.extend(_replace_paragraph_text(state.draft_document, paragraph_id, new_text))
            state.repair_history.append({
                "action": action,
                "paragraph_id": paragraph_id,
                "evidence_count": len(evidence_patch),
            })
        elif action_type == "drop_unsupported_claim" and paragraph_id:
            p = _find_paragraph(state.draft_document, paragraph_id)
            if repair_verbose and p:
                print_agent_long_preview(
                    f"【⑤ Patch】 drop 前原文 ({paragraph_id}) Agent:",
                    p.text,
                    max_chars=2000,
                    max_lines=40,
                )
            touched_paragraph_ids.extend(_drop_claim_text(state.draft_document, paragraph_id))
            if repair_verbose and p:
                print_agent_long_preview(
                    f"【⑤ Patch】 drop 后同段正文 ({paragraph_id}) Agent:",
                    p.text,
                    max_chars=2000,
                    max_lines=20,
                )
            state.repair_history.append({"action": action, "paragraph_id": paragraph_id})
        elif action_type == "append_missing_module" and not paragraph_id:
            new_text = rewrite_single_paragraph(
                llm=llm,
                stage_title=state.stage_title,
                paragraph_text="请新增一个简洁段落，补充当前阶段缺失的关键问题回答。",
                evidence_patch=evidence_patch,
                action=action,
                paragraph_id="(新段落)",
                log_io=repair_verbose,
            )
            before_n = len(state.draft_document.paragraphs)
            touched_paragraph_ids.extend(_append_paragraph(state.draft_document, new_text, evidence_patch))
            if repair_verbose and touched_paragraph_ids:
                np = _find_paragraph(state.draft_document, touched_paragraph_ids[-1])
                if np:
                    print(
                        f"   📥 ⑤ 已追加段落 {np.paragraph_id}（文档段落数 {before_n} → {len(state.draft_document.paragraphs)}）"
                    )
                    print_agent_long_preview(
                        f"【⑤ Patch】 新段落全文预览 ({np.paragraph_id}) Agent:",
                        np.text,
                        max_chars=4000,
                        max_lines=100,
                    )
            state.repair_history.append({
                "action": action,
                "paragraph_id": touched_paragraph_ids[-1] if touched_paragraph_ids else "",
                "evidence_count": len(evidence_patch),
            })

    state.draft_markdown = state.draft_document.to_markdown()
    state.status = "patched"
    if repair_verbose:
        order = [p.paragraph_id for p in state.draft_document.paragraphs]
        print("\n   🧩 ⑤ 草稿拼接说明:")
        print(f"      · DraftDocument 共 {len(state.draft_document.paragraphs)} 段，按序 id: {order[:12]}{'…' if len(order) > 12 else ''}")
        print("      · 规则: `to_markdown()` = 各段 `paragraph.text.strip()` 用 \\n\\n 连接（无标题层级注入）")
        print(f"      · 本轮 touched 段落: {list(dict.fromkeys(touched_paragraph_ids)) or '（无）'}")
        print(f"      · 拼接后 draft_markdown 总长约 {len(state.draft_markdown):,} 字符")
        print_agent_long_preview(
            "【⑤ Patch】 拼接后全章开头预览 Agent:",
            state.draft_markdown,
            max_chars=4500,
            max_lines=90,
        )
    return list(dict.fromkeys(touched_paragraph_ids))
