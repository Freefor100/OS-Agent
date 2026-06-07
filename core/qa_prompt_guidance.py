from __future__ import annotations

from typing import Iterable, List


FIELD_GUIDANCE = {
    "structured_facts": "structured_facts 是必须逐项完成的事实表；每个 fact 都需要可追溯证据或明确 unknown。",
    "answer_contract": "answer_contract 约束最终 value 的类型、枚举、固定字段和证据引用规则。",
    "concept_boundary": "concept_boundary 是防混淆边界；相似概念不能互相替代。",
    "diagnostic_checks": "diagnostic_checks 是局部判断步骤；复杂题需要逐条查证。",
    "tri_state_rule": "tri_state_rule 定义 implemented / stub / not_found / unknown 的判定边界。",
    "anti_examples": "anti_examples 是反例；命中反例时不能判 implemented。",
    "evidence_policy": "evidence_policy 定义强证据类型和 not_found 所需的负向搜索覆盖。",
    "llm_answer_steps": "llm_answer_steps 是建议作答顺序；不得替代证据。",
    "choices": "choices 是选择题合法值；single_choice 必须原文命中其中一项，multi_choice 必须返回数组。",
}


def field_guidance(fields: Iterable[str]) -> str:
    """Return concise guidance only for QA fields visible in the current prompt."""
    seen = set()
    lines: List[str] = []
    for field in fields:
        key = str(field or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        text = FIELD_GUIDANCE.get(key)
        if text:
            lines.append(f"- {text}")
    if not lines:
        return ""
    return "题单字段说明：\n" + "\n".join(lines) + "\n"


def evidence_discipline_guidance() -> str:
    return (
        "- RAG/grep 命中只能作为 hint；implemented 需要 read/LSP/function body/call-site 等强证据。\n"
        "- not_found 需要覆盖 evidence_policy/structured_facts 中关键词和 seed_paths 的结构化负向搜索。\n"
    )


def answer_shape_guidance() -> str:
    return (
        "- 必须为 Question.structured_facts 中每个 fact_id 输出一个 fact_answers item，字段为 fact_id, fact_key, value, used_evidence_ids, notes。\n"
        "- 若 fact 定义 allowed_values，fact_answers[*].value 必须使用其中一个枚举值；否则按 answer_type/fields 输出结构化值或 unknown。\n"
        "- 只有 Question.answer_contract.value_shape 明确给出字段时，short_answer/fill_in 的 value 才必须是固定字段 JSON object；否则 value 应直接回答题干。\n"
        "- tri_state_impl 的 value 只能是 implemented / stub / not_found / unknown。\n"
        "- used_evidence_ids 与 fact_answers[*].used_evidence_ids 只能引用当前题可见 Bound Evidence 的 evidence_id；不要输出 path、line、excerpt。\n"
    )
