# baseline_test.py
#
# 无工具 Baseline：将完整仓库源码 + 题单（已剔除 Agent 工具相关约束）一次性送入 LLM，
# 对 02–09 题单各调用一次，不做 JSON 修复重试；然后走与主链路相同的 review，最终仅写
# baseline_output/<repo_name>/{_per_stage/*, review_score.json}，不生成合并 md 报告。
#
# 断点续传：某章 `_per_stage/<stage_id>_answers.json` 存在且仍能通过题库校验则跳过该章 Execute；
# 在「未在本轮重新跑 Execute」的前提下，若 `_per_stage/<stage_id>_review.json` 已存在且可解析则跳过 Review；
# 仅有 answers、缺 review 时只补跑 Review。全部章节 answers 均已命中时可跳过仓库平铺收集。
#
# Execute 单次用户消息极大（整仓平铺），默认 HTTP 读超时易不足：见 `BASELINE_REQUEST_TIMEOUT`（秒，默认 3600）。

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(override=True)

from langchain_core.messages import HumanMessage, SystemMessage

from core.agent_builder import build_chat_model, get_model_name
from core.describe_json_qa import (
    SCHEMA_VERSION as JSON_QA_SCHEMA_VERSION,
    coerce_answers_payload_by_stage_qa,
    coerce_answers_payload_defaults,
    parse_answers_json,
    validate_answers_payload,
)
from core.describe_stage_qa import list_question_ids, load_stage_qa
from core.describe_stage_review import (
    REVIEW_STAGES_02_09,
    build_stage_qa_question_sheet,
    enrich_review_with_report_quality,
    run_describe_stage_review,
    write_review_score_json,
)
from core.hf_env import apply_hf_hub_env_defaults
from core.utils import llm_message_total_tokens, repo_name_from_url

apply_hf_hub_env_defaults()

# 不含 RAG/LSP/工具调用 描述；与 JSON-QA 主链路输出要求一致
BASELINE_ANSWER_SYSTEM = """You are an elite Operating System Technical Analyst.
You will be given the full repository source text in the user message, plus a question sheet. Answer strictly from that source; do not invent file paths or symbols that are not in the provided tree.

## Core principles
1. Evidence-based. Never guess; cite repository-relative `path` and `excerpt` in each answer's `evidence`.
2. Reverse evidence: if not found, say so with `not_found` or the appropriate choice, and still give honest search/reading notes in `evidence.excerpt` when possible.
3. Strict tri_state_impl: use only `implemented` / `stub` / `not_found` when asked.
4. Your FINAL message must be a single JSON object and nothing else (no prose before/after). It must be parseable by `json.loads`.
5. If any `value` contains multi-line or Mermaid, JSON-escape newlines as `\\n` and quotes as `\\"`; do not break JSON with raw triple-backtick blocks inside string values."""


# 默认 2.4MB 用户内容上限，可用环境变量覆盖
def _max_user_chars() -> int:
    v = (os.environ.get("BASELINE_MAX_USER_CHARS") or "2400000").strip()
    try:
        n = int(v)
    except ValueError:
        n = 2_400_000
    return max(100_000, n)


def _baseline_request_timeout() -> int:
    """整仓一次送入时模型推理时间很长，须大于 core.agent_builder 默认的 240s。"""
    v = (os.environ.get("BASELINE_REQUEST_TIMEOUT") or "3600").strip()
    try:
        n = int(v)
    except ValueError:
        n = 3600
    return max(120, n)


# 与 os_agent 中 _build_json_qa_prompt 对齐，但去掉 stage_constraints_md（内多为工具指令），并弱化可能暗示工具的句式
def build_baseline_json_qa_prompt(stage_id: str, stage_title: str) -> tuple[str, list[str]]:
    stage_qa = load_stage_qa(stage_id)
    questions = stage_qa.get("questions", []) if isinstance(stage_qa, dict) else []
    expected_ids = list_question_ids(stage_qa)

    lines: list[str] = []
    lines.append("## 题单（评委用，小题作答）")
    lines.append("")
    for q in questions if isinstance(questions, list) else []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id", "")).strip()
        qtype = str(q.get("question_type", "")).strip()
        stem = str(q.get("stem", "")).strip()
        if not (qid and qtype and stem):
            continue
        lines.append(f"- **{qid}** ({qtype})：{stem}")
        choices = q.get("choices")
        if isinstance(choices, list) and choices:
            for i, c in enumerate(choices):
                label = chr(ord("A") + i)
                lines.append(f"  - {label}. {str(c).strip()}")
    lines.append("")

    lines.append("## 必须回答")
    lines.append("")
    for q in questions if isinstance(questions, list) else []:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("question_id", "")).strip()
        stem = str(q.get("stem", "")).strip()
        if qid and stem:
            lines.append(f"- [{qid}] {stem}")
    lines.append("")

    lines.append("## 分析原则（必须遵守，Baseline 无外部工具）")
    lines.append("")
    lines.append(
        "**等价实现原则**：题目中出现的算法名、函数名、结构体名、宏名、系统调用名，"
        "只是候选关键词或示例，**不**一定与仓库中的标识符逐字相同。"
        "若存在语义等价的实现，请按“等价实现/等价接口/等价结构”分析，"
        "不要因某个名字未出现就一律报 `not_found`；但也**禁止**无证据的臆断。"
    )
    lines.append("")
    lines.append(
        "**范围**：下文附带完整仓库源码，请**仅**依据该内容作答；`evidence` 中的 `path` 必须能在该内容中出现，"
        "或给出你在该内容中的检索/阅读过程说明（在 `excerpt` 中）。**停止条件**：一旦能稳定答完当前题，不要横向堆砌无关子系统。"
    )
    lines.append("")

    lines.append("## 阅读提示（非强制步骤）")
    lines.append(
        "可按目录/文件名/关键字自行在下方源码中定位；不指定任何 IDE 或 Agent 工具名称。"
    )
    lines.append("")

    lines.append("## 输出契约（严格）")
    lines.append("")
    lines.append("你在本阶段**最终输出**必须是**唯一一个 JSON 对象**（允许使用 ```json 围栏包裹），不得输出任何额外解释文字。")
    lines.append("JSON 顶层字段必须包含：`schema_version`、`stage_id`、`stage_title`、`terminology_profile`、`answers`。")
    lines.append("其中 `answers` 是数组，每个元素必须包含：`question_id`、`question_type`、`stem`、`value`、`evidence`。")
    lines.append("`tri_state_impl` 的 `value` 只允许：`implemented` / `stub` / `not_found`。")
    lines.append("### 选择题约束（必须严格遵守，否则视为无效答案）")
    lines.append("")
    lines.append("**single_choice（单选）**：")
    lines.append("- `value` 必须是该题 `choices[]` 中的**某一项的完整原文**，要求**逐字匹配**（完全相等）。")
    lines.append("- **禁止**输出 `A/B/C/D` 或 `A.`/`B.` 前缀；禁止输出 `1/2/3` 编号；禁止改写/同义改写/缩写；禁止附加解释。")
    lines.append("- 若证据不足以确定选哪一项，必须选择 `choices[]` 中语义最接近且包含 **“未发现/待核实/不支持/未实现”** 的那一项（若存在）。")
    lines.append("")
    lines.append("**multi_choice（多选）**：")
    lines.append("- `value` 必须是数组（JSON array）。数组中**每个元素**都必须是该题 `choices[]` 中的**完整原文**，要求逐字匹配。")
    lines.append("- **禁止**输出 `A/C`、`A,C`、`[\"A\",\"C\"]` 这类字母代号；禁止输出带 `A.` 前缀的文本；禁止改写选项。")
    lines.append(
        "每条证据 `evidence[]` 必须包含：`path`（仓库相对路径）、`symbol_kind`、`symbol_name`、"
        "`excerpt`（**否定/未找到结论时见上节须为非空**，其它题型仍建议填写摘录）。"
    )
    lines.append("")
    lines.append(
        "你必须使用本仓库代码证据作答。若未发现实现，按三态要求输出 `not_found`。"
        "**不得编造**不存在的文件路径或符号；**鼓励**在 `evidence` 中给出可复核的说明（在 Baseline 中可为阅读/搜索要点）。"
    )
    lines.append("")
    lines.append("### `not_found` / 否定结论时的证据（强烈建议非空）")
    lines.append("")
    lines.append(
        "当结论为 `not_found` 或选择题/简答表达「未发现」时，`evidence` **优先使用 1～3 条**真实记录："
    )
    lines.append("- `path`：你实际在下方源码中看到的**真实**相对路径，或你重点浏览过的目录。")
    lines.append("- `symbol_kind`：可用 `search`、`read`、`list` 等自说明类别（字符串即可）。")
    lines.append(
        "- `excerpt`：**必填（此场景下）**，写清在附件源码中的检索要点、范围与结论（如「在附件中未见 xxx 符号」）。"
    )
    lines.append("")
    lines.append("### Mermaid / 多行文本与 JSON 合法性（极其重要）")
    lines.append("")
    lines.append(
        "最终输出必须是 **`json.loads` 一次即可解析** 的合法 JSON。字符串值内的 **物理换行必须写成 `\\n`**，"
        "字符串内的 **双引号必须写成 `\\\"`**，反斜杠写成 `\\\\`。"
    )
    lines.append(
        "**严禁**在 `value` 的 JSON 字符串中直接嵌入「含真实换行」的 ```mermaid … ``` 围栏块。"
    )
    lines.append("若题干要求 Mermaid，任选其一：将图放在**单行**内用 `\\n` 连起来；或改为步骤列表；并保证 JSON 合法。")
    lines.append("**禁止**输出「看起来像 JSON、实际不能解析」的内容；宁可简化图，不可输出非法 JSON。")
    lines.append("")
    lines.append("你必须按题单顺序输出 answers，且 question_id 必须与题单完全一致（不多不少）。")
    lines.append("")
    lines.append("JSON 示例（缩略，仅示意字段；不要复用其中路径/符号）：")
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append(f"  \"schema_version\": \"{JSON_QA_SCHEMA_VERSION}\",")
    lines.append(f"  \"stage_id\": \"{stage_id}\",")
    lines.append(f"  \"stage_title\": \"{stage_title}\",")
    lines.append("  \"terminology_profile\": \"stallings_en_zh\",")
    lines.append("  \"answers\": [")
    lines.append("    {")
    lines.append("      \"question_id\": \"QXX_001\",")
    lines.append("      \"question_type\": \"tri_state_impl\",")
    lines.append("      \"stem\": \"...\",")
    lines.append("      \"value\": \"not_found\",")
    lines.append("      \"evidence\": [")
    lines.append("        {")
    lines.append("          \"path\": \"kernel/syscall/sysnum.h\",")
    lines.append("          \"symbol_kind\": \"search\",")
    lines.append("          \"symbol_name\": \"keyword_scan\",")
    lines.append("          \"excerpt\": \"在附件源码中检索 xxx，未命中相关实现。\"")
    lines.append("        }")
    lines.append("      ]")
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines).strip() + "\n", expected_ids


_CODE_EXT = {
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hpp",
    ".rs",
    ".S",
    ".s",
    ".asm",
    ".go",
    ".py",
    ".toml",
    ".ld",
    ".lds",
    ".dts",
    ".dtsi",
    ".mk",
    ".inc",
    ".sh",
    ".zig",
    ".kconfig",
    ".in",
    ".ldd",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".ldscript",
    ".lds.S",
    ".cmake",
    ".pl",
    ".pm",
    ".rlib",
    ".boot",
    ".gdb",
}
# 仅用于 os.walk：这些**子目录名**不递归进入（跳过 .git / 常见构建与依赖目录），避免把无关节点打包进附言。
# 不表示「在正文里省略路径」——每个文件块仍带相对仓库根的路径（见 collect_repo_text）。
_SKIP_DIR_NAMES = {
    ".git",
    "target",
    "build",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "out",
    "cmake-build",
    "cmake-build-debug",
    "cmake-build-release",
    "zig-cache",
    "zig-out",
    "deps",
    "incremental",
    "debug",
    "release",
    ".idea",
    ".vs",
}  # 只按目录名匹配；显式列出不笼统跳过所有「点目录」，以免误伤 `.github` 等


def _repo_rel_posix(repo_root: str, file_path: str) -> str:
    """相对仓库根的路径，统一用正斜杠，便于与题单 evidence 中的 path 风格一致（跨平台）。"""
    rel = os.path.relpath(file_path, repo_root)
    return rel.replace("\\", "/").lstrip("/")


def _is_skipped_dir(name: str) -> bool:
    n = name.lower()
    if n in {x.lower() for x in _SKIP_DIR_NAMES}:
        return True
    if n in (".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox"):
        return True
    return False


def _should_include_file(path: str) -> bool:
    base = os.path.basename(path)
    if base.startswith(".") and base not in (".", ".."):
        if base in (".clang-format", ".editorconfig", ".gitignore"):
            return True
        if not base.lower().endswith((".c", ".h", ".S", "ignore")):
            return False
    ext = os.path.splitext(path)[1].lower()
    if not ext and base in ("Makefile", "makefile", "GNUmakefile", "Doxyfile", "Kbuild", "Kconfig"):
        return True
    if not ext and ("Makefile." in base or base.endswith(".mk")):
        return True
    return ext in _CODE_EXT or ext == "" and base in ("README", "README.md", "build.rs", "Cargo.toml", "clippy.toml", "rustfmt.toml")


def collect_repo_text(repo_path: str) -> str:
    """将所有可读源码按路径排序后拼接为一个大块。每个文件以「相对仓库根、正斜杠」路径作为 FILE 行（路径信息不丢、风格统一）。"""
    root_norm = os.path.normpath(os.path.abspath(repo_path))
    parts: list[str] = []
    for root, dirs, files in os.walk(repo_path, topdown=True):
        dirs[:] = [d for d in sorted(dirs) if not _is_skipped_dir(d)]
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = _repo_rel_posix(root_norm, os.path.normpath(full))
            if not _should_include_file(full):
                continue
            if os.path.getsize(full) > 1_200_000:
                parts.append(f"\n\n# === FILE: {rel} (SKIPPED, too large) ===\n\n")
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError as e:
                parts.append(f"\n\n# === FILE: {rel} (READ ERROR: {e}) ===\n\n")
                continue
            parts.append(f"\n\n# === FILE: {rel} ===\n{body}\n")
    if not parts:
        return ""
    header = (
        f"# === REPO_ROOT: {root_norm} ===\n"
        "# 以下每行 FILE 为相对此根的仓库路径（正斜杠）；JSON evidence.path 应与此处一致，勿写绝对盘符。"
        "\n"
    )
    return (header + "\n".join(parts)).strip() + "\n"


def _truncate(s: str, max_chars: int) -> tuple[str, bool]:
    """若 s 超过 max_chars，只保留前段并加英文提示行；否则原样返回。第二项为是否发生过截断。"""
    if max_chars <= 0:
        return "", True
    if len(s) <= max_chars:
        return s, False
    return (
        f"[BASELINE: TRUNCATED from {len(s)} to {max_chars} chars, beginning kept]\n\n"
        + s[:max_chars],
        True,
    )


def _save_json(path: str, obj: object) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _load_validated_answers_json(
    per_stage: str,
    stage_id: str,
    stage_title: str,
    expected_question_ids: list[str],
) -> dict | None:
    """磁盘上 answers.json 存在且通过 coerce+validate 则返回覆写后的 payload，否则 None。"""
    if not expected_question_ids:
        return None
    json_path = os.path.join(per_stage, f"{stage_id}_answers.json")
    if not os.path.isfile(json_path) or os.path.getsize(json_path) < 16:
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        stage_qa = load_stage_qa(stage_id)
        payload = coerce_answers_payload_defaults(payload)
        payload2 = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
        issues = validate_answers_payload(
            payload2,
            stage_id=stage_id,
            stage_title=stage_title,
            expected_question_ids=expected_question_ids,
        )
        if issues:
            return None
        return payload2
    except Exception:
        return None


def _review_json_complete(review_path: str) -> bool:
    if not os.path.isfile(review_path) or os.path.getsize(review_path) < 16:
        return False
    try:
        with open(review_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return isinstance(data, dict)
    except Exception:
        return False


def _baseline_any_stage_needs_repo_execute(per_stage: str) -> bool:
    """任一章缺有效 answers.json 则需要拉平仓库文本并跑 Execute。"""
    for stage_id in REVIEW_STAGES_02_09:
        st_qa = load_stage_qa(stage_id)
        title = (st_qa.get("stage_title") if isinstance(st_qa, dict) else None) or stage_id
        _, expected_ids = build_baseline_json_qa_prompt(stage_id, str(title))
        if not expected_ids:
            continue
        if _load_validated_answers_json(per_stage, stage_id, str(title), expected_ids) is None:
            return True
    return False


def _material_b_for_review(
    *,
    ok: bool,
    stage_text: str,
    stage_id: str,
    payload_before: dict | None,
    err: str | None,
    issues: list | None,
) -> str:
    if ok and payload_before is not None:
        return json.dumps(payload_before, ensure_ascii=False, indent=2)
    d: dict = {
        "baseline_status": "parse_or_validate_failed",
        "error": (err or "unknown")[:20_000],
    }
    if issues:
        d["validate_issues"] = [
            f"{getattr(x, 'path', '')}: {getattr(x, 'reason', str(x))}" for x in issues
        ][:200]
    tail = 120_000
    d["raw_model_output_excerpt"] = (stage_text or "")[:tail]
    if len(stage_text or "") > tail:
        d["excerpt_note"] = f"（完整原文见 {stage_id}_answers_raw.txt，此处截断 {tail} 字符）"
    return json.dumps(d, ensure_ascii=False, indent=2)


def main() -> None:
    # 与主管线一致地强制开启 Review
    os.environ["DESCRIBE_STAGE_REVIEW"] = "1"

    repo_url = (os.environ.get("REPO_URL") or "").strip()
    if not repo_url:
        print("错误：未设置 REPO_URL（请在 .env 中设置）", file=sys.stderr)
        sys.exit(1)

    repo_name = repo_name_from_url(repo_url)
    repo_output_dir = os.path.join("baseline_output", repo_name)
    per_stage = os.path.join(repo_output_dir, "_per_stage")
    os.makedirs(per_stage, exist_ok=True)

    repo_local_path = os.path.normpath(os.path.join("./repos", repo_name))
    if os.path.isdir(repo_local_path) and os.listdir(repo_local_path):
        print(f"使用已有仓库: {repo_local_path}")
    else:
        print(f"正在克隆: {repo_url} …")
        from tools.git_ops import clone_repository

        print(clone_repository.invoke({"repo_url": repo_url}))

    need_repo_execute = _baseline_any_stage_needs_repo_execute(per_stage)
    max_user = _max_user_chars()
    max_blob = max(100_000, max_user - 120_000)
    repo_blob = ""
    repo_was_trunc = False
    if need_repo_execute:
        print("收集仓库文本…")
        repo_blob = collect_repo_text(repo_local_path)
        if not repo_blob.strip():
            print("错误：未读到任何源文件，请检查仓库路径。", file=sys.stderr)
            sys.exit(1)
        repo_blob, repo_was_trunc = _truncate(repo_blob, max_blob)
        if repo_was_trunc:
            print(
                f"仓库文本长度: {len(repo_blob):,} 字符  （已截断：单条用户消息总上限 {max_user:,}，"
                f"平铺部分上限 max_blob={max_blob:,}，超出部分已丢弃，仅保开头）"
            )
        else:
            print(
                f"仓库文本长度: {len(repo_blob):,} 字符  （未截断；平铺上限 max_blob={max_blob:,}，"
                f"单条用户消息总上限 {max_user:,}，可用环境变量 BASELINE_MAX_USER_CHARS 调大）"
            )
    else:
        print(
            "⏭️  全部章节 answers.json 均已命中且校验通过：跳过仓库平铺收集（仅补跑缺失的 Review 等）"
        )

    execute_model_name = os.environ.get("MODEL_NAME") or get_model_name()
    req_to = _baseline_request_timeout()
    llm = build_chat_model(
        model=execute_model_name,
        temperature=0,
        max_retries=0,
        request_timeout=req_to,
    )
    print(f"Baseline Execute HTTP 读超时: {req_to}s（环境变量 BASELINE_REQUEST_TIMEOUT）")

    total_tokens_used = 0
    token_rows: list[dict] = []
    start_time = datetime.now()

    for stage_id in REVIEW_STAGES_02_09:
        st_qa = load_stage_qa(stage_id)
        title = (st_qa.get("stage_title") if isinstance(st_qa, dict) else None) or stage_id
        qa_user, expected_ids = build_baseline_json_qa_prompt(stage_id, str(title))
        if not expected_ids:
            print(f"跳过 {stage_id}：无题单", file=sys.stderr)
            continue

        cached_payload = _load_validated_answers_json(
            per_stage, stage_id, str(title), expected_ids
        )
        answers_from_cache = cached_payload is not None

        execute_tokens = 0
        stage_text = ""
        ok = False
        payload_before: dict | None = None
        err: str | None = None
        issues: list = []

        if answers_from_cache:
            print("=" * 60)
            print(f"⏭️  {stage_id} — {title}：跳过 Execute（answers.json 已存在且校验通过）")
            ok = True
            payload_before = copy.deepcopy(cached_payload)
        else:
            if not repo_blob.strip():
                print(
                    f"错误：{stage_id} 需要 Execute 但未收集到仓库文本（不应发生）。",
                    file=sys.stderr,
                )
                sys.exit(1)
            combined = (
                f"{qa_user}\n\n"
                f"---\n\n# 附：仓库 `{repo_name}` 根路径 `{repo_local_path}` 的源码平铺\n\n"
                f"```text\n{repo_blob}\n```"
            )
            if len(combined) > max_user:
                allow = max_user - (len(combined) - len(repo_blob)) - 10
                blob2, _ = _truncate(repo_blob, max(0, allow))
                combined = (
                    f"{qa_user}\n\n"
                    f"---\n\n# 附：仓库源码（因题单+围栏后总长度仍超单条上限 {max_user}，再次截断平铺，allow={max(0, allow)}）\n\n"
                    f"```text\n{blob2}\n```"
                )

            print("=" * 60)
            print(f"Baseline Execute: {stage_id} — {title}  (用户消息 ~{len(combined):,} 字)")
            msg = [SystemMessage(content=BASELINE_ANSWER_SYSTEM), HumanMessage(content=combined)]
            out = llm.invoke(msg)
            execute_tokens = llm_message_total_tokens(out)
            stage_text = (getattr(out, "content", None) or "").strip()
            if not stage_text:
                stage_text = ""

            raw_path = os.path.join(per_stage, f"{stage_id}_answers_raw.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(stage_text + "\n")

            try:
                payload = parse_answers_json(stage_text)
                payload = coerce_answers_payload_defaults(payload)
                payload_before = copy.deepcopy(payload)
                stage_qa = load_stage_qa(stage_id)
                payload2 = coerce_answers_payload_by_stage_qa(payload, stage_qa=stage_qa)
                issues = validate_answers_payload(
                    payload2,
                    stage_id=stage_id,
                    stage_title=str(title),
                    expected_question_ids=expected_ids,
                )
                if not issues:
                    ok = True
                    _save_json(os.path.join(per_stage, f"{stage_id}_answers.json"), payload2)
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                _save_json(
                    os.path.join(per_stage, f"{stage_id}_answers_error.json"),
                    {"error": err},
                )
            if issues and ok is False and err is None:
                _save_json(
                    os.path.join(per_stage, f"{stage_id}_answers_validate_issues.json"),
                    {"issues": [{"path": x.path, "reason": x.reason} for x in issues]},
                )
                err = f"validate issues: {len(issues)}"

        review_path = os.path.join(per_stage, f"{stage_id}_review.json")
        skip_review = answers_from_cache and _review_json_complete(review_path)
        review_tokens = 0
        parsed_review = None
        review_raw: str | None = None
        review_err: str | None = None

        if skip_review:
            print(f"⏭️  {stage_id}：跳过 Review（review.json 已存在且可解析）")
        else:
            model_b = _material_b_for_review(
                ok=ok,
                stage_text=stage_text,
                stage_id=stage_id,
                payload_before=payload_before,
                err=err,
                issues=issues,
            )
            if len(model_b) > 190_000:
                model_b = model_b[:190_000] + "\n... [material B hard truncated]"

            question_sheet = build_stage_qa_question_sheet(stage_id, str(title))
            print(f"Review: {stage_id} …")
            parsed_review, review_raw, review_err, review_tokens = run_describe_stage_review(
                stage_id=stage_id,
                stage_title=str(title),
                question_sheet=question_sheet,
                model_json_before_stage_qa_coerce=model_b,
                expected_question_ids=list(expected_ids),
            )

        stage_total_tokens = execute_tokens + review_tokens
        total_tokens_used += stage_total_tokens
        print(
            f"   Token  Execute +{execute_tokens:,}  Review +{review_tokens:,}  "
            f"小计 +{stage_total_tokens:,}  → 累计 {total_tokens_used:,}"
        )
        token_rows.append(
            {
                "stage_id": stage_id,
                "stage_title": str(title),
                "execute_total_tokens": execute_tokens,
                "review_total_tokens": review_tokens,
                "stage_total_tokens": stage_total_tokens,
            }
        )
        if skip_review:
            pass
        elif parsed_review is not None:
            p = copy.deepcopy(payload_before) if ok and payload_before else {}
            if not isinstance(p, dict):
                p = {}
            parsed_review = enrich_review_with_report_quality(parsed_review, p)
            meta = (
                dict(parsed_review["_meta"])
                if isinstance(parsed_review.get("_meta"), dict)
                else {}
            )
            meta["review_model"] = os.environ.get("DESCRIBE_REVIEW_MODEL") or os.environ.get("MODEL_NAME", "")
            meta["baseline"] = True
            meta["run_at"] = datetime.now().isoformat(timespec="seconds")
            meta["baseline_execute_tokens"] = execute_tokens
            meta["baseline_review_tokens"] = review_tokens
            meta["baseline_stage_total_tokens"] = stage_total_tokens
            parsed_review["_meta"] = meta
            _save_json(review_path, parsed_review)
            print(
                f"  OK  review -> {review_path}  rqs={parsed_review.get('report_quality_score')}"
            )
        else:
            err_p = os.path.join(per_stage, f"{stage_id}_review_error.json")
            _save_json(
                err_p,
                {
                    "error": review_err or "unknown",
                    "raw_model_output_excerpt": (review_raw or "")[:8000],
                },
            )
            print(f"  警告: Review 解析失败 -> {err_p}")

    _save_json(
        os.path.join(repo_output_dir, "token_usage.json"),
        {
            "schema_version": "baseline_token_usage_v1",
            "repo_name": repo_name,
            "execute_model": execute_model_name,
            "review_model": (os.environ.get("DESCRIBE_REVIEW_MODEL") or os.environ.get("MODEL_NAME") or ""),
            "total_tokens": total_tokens_used,
            "per_stage": token_rows,
            "note": "与 os_agent_d_describe.print_step 同源（response_metadata.token_usage.total_tokens）；若为 0 多表示本轮响应未带用量，以计费/控制台为准。",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_seconds": round(
                (datetime.now() - start_time).total_seconds(), 2
            ),
        },
    )

    try:
        bundle = write_review_score_json(repo_output_dir)
        print("=" * 60)
        print(f"已写入: {os.path.join(repo_output_dir, 'review_score.json')}")
        if isinstance(bundle, dict) and bundle.get("total_0_100") is not None:
            print(f"总分 (02–09 均值): {bundle.get('total_0_100')}/100")
    except OSError as e:
        print(f"写入 review_score.json 失败: {e}", file=sys.stderr)

    print("=" * 60)
    print(f"   总Token使用: {total_tokens_used:,}")
    print(f"   用量明细: {os.path.join(repo_output_dir, 'token_usage.json')}")


if __name__ == "__main__":
    main()
