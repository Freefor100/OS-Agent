# evaluate.py
"""
OS 分析报告评估程序

使用 Agent（带工具）自主查找仓库内的人类文档，与 Agent 生成的报告进行深度对比：
1. 内容覆盖度评分（Agent 覆盖了人类文档多少内容）
2. 准确性评分（Agent 描述与人类文档是否一致）
3. 详细度评分（Agent 是否提供了更多技术细节）
4. 亮点分析（Agent 比人类文档更详细/更好的地方）
5. 缺失分析（Agent 遗漏的重要内容）

特点：
- 使用 Agent 自主探索仓库，选择性读取重要文档
- 限制只能访问 OS 仓库和 output 目录
- 输出综合评分 + 详细评估报告
"""

import argparse
import json
import os
import sys
from datetime import datetime
from functools import partial

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# 评估维度定义
EVALUATION_DIMENSIONS = {
    "coverage": "内容覆盖度 - Agent 报告覆盖了人类文档中多少关键技术点",
    "accuracy": "准确性 - Agent 的技术描述与人类文档是否一致，有无错误",
    "depth": "技术深度 - Agent 是否深入到代码/实现层面，而非泛泛而谈",
    "structure": "结构完整性 - 报告结构是否清晰、完整、符合技术文档规范",
    "citations": "证据引用 - 是否引用了具体的文件路径、函数名、代码片段",
}

# 默认模型配置（可通过环境变量 MODEL_NAME 覆盖）
DEFAULT_MODEL = os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")


# ============================================================
# 受限工具定义 - 只能访问指定目录
# ============================================================

def _is_path_allowed(path: str, allowed_roots: list[str]) -> bool:
    """检查路径是否在允许的根目录下"""
    abs_path = os.path.abspath(path)
    for root in allowed_roots:
        abs_root = os.path.abspath(root)
        if abs_path.startswith(abs_root):
            return True
    return False


def create_restricted_tools(repo_path: str, output_path: str):
    """
    创建受限的文件操作工具，只能访问 repo_path 和 output_path
    """
    allowed_roots = [repo_path, output_path]
    
    @tool
    def list_directory(path: str, max_depth: int = 2) -> str:
        """
        列出目录结构。
        
        Args:
            path: 要列出的目录路径
            max_depth: 最大递归深度（默认 2）
        
        Returns:
            目录结构的文本表示
        """
        if not _is_path_allowed(path, allowed_roots):
            return f"❌ 错误：不允许访问路径 '{path}'。只能访问仓库目录和 output 目录。"
        
        if not os.path.isdir(path):
            return f"❌ 错误：'{path}' 不是有效目录。"
        
        result = []
        
        def walk(current_path: str, depth: int, prefix: str = ""):
            if depth > max_depth:
                return
            
            try:
                items = sorted(os.listdir(current_path))
            except PermissionError:
                return
            
            # 过滤掉不需要的目录
            skip_dirs = {".git", "__pycache__", "node_modules", "target", "vendor", ".venv"}
            
            for i, item in enumerate(items):
                item_path = os.path.join(current_path, item)
                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "
                
                if os.path.isdir(item_path):
                    if item in skip_dirs:
                        continue
                    result.append(f"{prefix}{connector}{item}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    walk(item_path, depth + 1, new_prefix)
                else:
                    # 添加文件大小信息
                    try:
                        size = os.path.getsize(item_path)
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024 * 1024:
                            size_str = f"{size/1024:.1f}KB"
                        else:
                            size_str = f"{size/(1024*1024):.1f}MB"
                    except:
                        size_str = "?"
                    result.append(f"{prefix}{connector}{item} ({size_str})")
        
        result.append(f"{os.path.basename(path)}/")
        walk(path, 0, "")
        return "\n".join(result[:200])  # 限制输出行数
    
    @tool
    def read_file(file_path: str, max_chars: int = 20000) -> str:
        """
        读取文件内容。支持 .md, .txt, .rst, .pdf 等格式。
        
        Args:
            file_path: 文件路径
            max_chars: 最大读取字符数（默认 20000）
        
        Returns:
            文件内容
        """
        if not _is_path_allowed(file_path, allowed_roots):
            return f"❌ 错误：不允许访问文件 '{file_path}'。只能访问仓库目录和 output 目录。"
        
        if not os.path.isfile(file_path):
            return f"❌ 错误：'{file_path}' 不是有效文件。"
        
        ext = os.path.splitext(file_path)[1].lower()
        
        # PDF 文件
        if ext == ".pdf":
            try:
                import PyPDF2
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    parts = []
                    for page in reader.pages[:30]:
                        text = page.extract_text()
                        if text:
                            parts.append(text)
                    content = "\n".join(parts)
                    if len(content) > max_chars:
                        content = content[:max_chars] + f"\n\n... [已截断，原文更长]"
                    return content
            except ImportError:
                return "⚠️ 未安装 PyPDF2，无法读取 PDF 文件。"
            except Exception as e:
                return f"❌ 读取 PDF 失败: {e}"
        
        # 文本文件
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n... [已截断，原文 {len(content)} 字符]"
            return content
        except Exception as e:
            return f"❌ 读取文件失败: {e}"
    
    @tool
    def find_documents(path: str, pattern: str = "") -> str:
        """
        在指定目录下搜索文档文件（.md, .txt, .rst, .pdf 等）。
        
        Args:
            path: 搜索的根目录
            pattern: 可选的文件名匹配模式（支持 * 通配符）
        
        Returns:
            找到的文档文件列表
        """
        if not _is_path_allowed(path, allowed_roots):
            return f"❌ 错误：不允许访问路径 '{path}'。只能访问仓库目录和 output 目录。"
        
        if not os.path.isdir(path):
            return f"❌ 错误：'{path}' 不是有效目录。"
        
        doc_extensions = {".md", ".txt", ".rst", ".pdf", ".doc", ".docx"}
        skip_dirs = {".git", "__pycache__", "node_modules", "target", "vendor", ".venv"}
        
        found = []
        for root, dirs, files in os.walk(path):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in doc_extensions:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, path)
                    
                    # 可选的模式匹配
                    if pattern:
                        import fnmatch
                        if not fnmatch.fnmatch(f.lower(), pattern.lower()):
                            continue
                    
                    try:
                        size = os.path.getsize(full_path)
                        if size < 1024:
                            size_str = f"{size}B"
                        elif size < 1024 * 1024:
                            size_str = f"{size/1024:.1f}KB"
                        else:
                            size_str = f"{size/(1024*1024):.1f}MB"
                    except:
                        size_str = "?"
                    
                    found.append(f"{rel_path} ({size_str})")
        
        if not found:
            return f"未找到匹配的文档文件。"
        
        return f"找到 {len(found)} 个文档文件:\n" + "\n".join(found[:50])
    
    return [list_directory, read_file, find_documents]


# ============================================================
# 评估 Agent 构建
# ============================================================

EVAL_SYSTEM_PROMPT = """你是一个专业的操作系统技术文档评审专家。

## 你的任务
对比分析 Agent 自动生成的 OS 技术分析报告与仓库内人类撰写的原始文档，给出评分和详细分析。

## 可用工具
你有以下工具来探索文件：
- `list_directory`: 列出目录结构，了解仓库和输出目录的内容
- `find_documents`: 搜索文档文件（.md, .pdf 等）
- `read_file`: 读取具体文件内容

## 安全限制
你只能访问以下目录：
1. OS 仓库目录（人类文档所在位置）
2. output 目录（Agent 报告所在位置）

## 评估维度（每项 0-100 分）
1. **coverage（内容覆盖度）**: Agent 报告覆盖了人类文档中多少关键技术点？
2. **accuracy（准确性）**: Agent 的技术描述与人类文档/代码实际是否一致？
3. **depth（技术深度）**: Agent 是否深入到代码实现层面（引用具体文件、函数）？
4. **structure（结构完整性）**: 报告结构是否清晰、符合技术文档规范？
5. **citations（证据引用）**: 是否有具体的文件路径、代码片段引用？

## 工作流程
1. 首先使用 `list_directory` 了解仓库结构
2. 使用 `find_documents` 找到人类撰写的文档（README、设计文档等）
3. 使用 `read_file` 读取 Agent 报告和关键的人类文档
4. 对比分析后，输出最终评估结果

## 最终输出格式（必须严格遵循）

完成分析后，你必须输出以下格式的 JSON（用 ```json ``` 包裹）：

```json
{
    "overall_score": <0-100 综合评分>,
    "dimension_scores": {
        "coverage": <0-100>,
        "accuracy": <0-100>,
        "depth": <0-100>,
        "structure": <0-100>,
        "citations": <0-100>
    },
    "highlights": [
        "<Agent 报告比人类文档更详细/更好的地方 1>",
        "<Agent 报告比人类文档更详细/更好的地方 2>"
    ],
    "missing": [
        "<Agent 遗漏的人类文档中的重要内容 1>",
        "<Agent 遗漏的人类文档中的重要内容 2>"
    ],
    "errors": [
        "<Agent 报告中的错误描述（如有）>"
    ],
    "human_docs_reviewed": [
        "<你读取的人类文档路径 1>",
        "<你读取的人类文档路径 2>"
    ],
    "summary": "<100-200字的总体评价>",
    "comparison_details": "<300-500字的详细对比分析>"
}
```

## 重要提示
- 如果 Agent 报告比人类文档更详细、更专业，这是**加分项**，应该在 highlights 中列出
- 如果人类文档本身很简略（如只有简单 README），而 Agent 提供了丰富的技术分析，给高分
- 客观公正，基于实际内容质量评分
"""


def build_eval_agent(repo_path: str, output_path: str, model: str = None):
    """构建评估 Agent
    
    Args:
        repo_path: 仓库路径
        output_path: 输出目录
        model: 模型名称，不指定则使用环境变量 MODEL_NAME 或默认值
    """
    tools = create_restricted_tools(repo_path, output_path)
    model_name = model or DEFAULT_MODEL
    llm = ChatOpenAI(model=model_name, temperature=0)
    agent = create_react_agent(llm, tools)
    return agent


# ============================================================
# 评估报告生成
# ============================================================

def generate_evaluation_report(
    result: dict,
    agent_report_path: str,
    repo_path: str,
) -> str:
    """生成评估报告 Markdown"""
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    repo_name = os.path.basename(repo_path.rstrip("/\\"))
    
    report = f"""# 📊 OS 分析报告评估结果

**评估时间**: {now}  
**项目名称**: {repo_name}  
**Agent 报告**: `{agent_report_path}`  

---

## 🎯 综合评分: {result.get('overall_score', 'N/A')}/100

"""
    
    # 维度评分
    dim_scores = result.get("dimension_scores", {})
    if dim_scores:
        report += "### 分维度评分\n\n"
        report += "| 维度 | 评分 | 说明 |\n"
        report += "|------|------|------|\n"
        for dim, desc in EVALUATION_DIMENSIONS.items():
            score = dim_scores.get(dim, "N/A")
            if isinstance(score, (int, float)):
                if score >= 80:
                    emoji = "🟢"
                elif score >= 60:
                    emoji = "🟡"
                else:
                    emoji = "🔴"
            else:
                emoji = "⚪"
            report += f"| {dim} | {emoji} {score} | {desc} |\n"
        report += "\n"
    
    # 对比的人类文档
    human_docs = result.get("human_docs_reviewed", [])
    if human_docs:
        report += "### 对比的人类文档\n\n"
        for doc in human_docs:
            report += f"- `{doc}`\n"
        report += "\n"
    
    # 亮点
    highlights = result.get("highlights", [])
    if highlights:
        report += "---\n\n## ✨ Agent 报告亮点（优于人类文档的地方）\n\n"
        for i, h in enumerate(highlights, 1):
            report += f"{i}. {h}\n"
        report += "\n"
    
    # 缺失
    missing = result.get("missing", [])
    if missing:
        report += "---\n\n## ⚠️ 缺失内容（Agent 未覆盖的重要信息）\n\n"
        for i, m in enumerate(missing, 1):
            report += f"{i}. {m}\n"
        report += "\n"
    
    # 错误
    errors = result.get("errors", [])
    if errors:
        report += "---\n\n## ❌ 错误或不准确的描述\n\n"
        for i, e in enumerate(errors, 1):
            report += f"{i}. {e}\n"
        report += "\n"
    
    # 总结
    summary = result.get("summary", "")
    if summary:
        report += f"---\n\n## 📝 总体评价\n\n{summary}\n\n"
    
    # 详细对比
    details = result.get("comparison_details", "")
    if details:
        report += f"---\n\n## 🔍 详细对比分析\n\n{details}\n\n"
    
    report += "---\n\n*本评估由 Agent 自动生成，仅供参考。*\n"
    
    return report


def extract_json_from_response(text: str) -> dict:
    """从 Agent 响应中提取 JSON"""
    # 尝试找到 JSON 块
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            json_str = text[start:end].strip()
            return json.loads(json_str)
    
    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            json_str = text[start:end].strip()
            if json_str.startswith("{"):
                return json.loads(json_str)
    
    # 尝试直接解析
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        json_str = text[start:end]
        return json.loads(json_str)
    
    raise ValueError("无法从响应中提取 JSON")


# ============================================================
# 主运行逻辑
# ============================================================

def run_evaluation(
    agent_report_path: str,
    repo_path: str,
    output_path: str = None,
    model: str = "deepseek/deepseek-v3.2",
) -> dict:
    """
    运行完整评估流程
    """
    print(f"\n{'='*60}")
    print("🔍 OS 分析报告评估程序（Agent 模式）")
    print(f"{'='*60}")
    
    # 规范化路径
    repo_path = os.path.abspath(repo_path)
    agent_report_path = os.path.abspath(agent_report_path)
    report_dir = os.path.dirname(agent_report_path)
    
    repo_name = os.path.basename(repo_path.rstrip("/\\"))
    
    print(f"\n📁 仓库路径: {repo_path}")
    print(f"📄 Agent 报告: {agent_report_path}")
    
    # 验证路径
    if not os.path.isdir(repo_path):
        print(f"❌ 仓库路径不存在: {repo_path}", file=sys.stderr)
        return {"overall_score": 0, "error": "仓库路径不存在"}
    
    if not os.path.isfile(agent_report_path):
        print(f"❌ Agent 报告不存在: {agent_report_path}", file=sys.stderr)
        return {"overall_score": 0, "error": "Agent 报告不存在"}
    
    # 构建评估任务
    eval_task = f"""## 评估任务

请评估以下 OS 项目的 Agent 自动分析报告质量。

### 信息
- **项目名称**: {repo_name}
- **仓库路径**: {repo_path}
- **Agent 报告路径**: {agent_report_path}

### 请执行以下步骤

1. **探索仓库结构**: 使用 `list_directory("{repo_path}")` 了解目录结构

2. **查找人类文档**: 使用 `find_documents("{repo_path}")` 列出所有文档文件
   - 重点关注: README.md, 设计文档, docs/ 目录下的文件

3. **读取 Agent 报告**: 使用 `read_file("{agent_report_path}")` 读取 Agent 生成的报告

4. **读取人类文档**: 选择最重要的 2-5 个人类文档进行读取对比
   - 优先级: README > 设计文档/架构文档 > 其他文档

5. **对比分析**: 分析 Agent 报告与人类文档的差异
   - Agent 覆盖了哪些内容？
   - Agent 遗漏了什么？
   - Agent 有哪些比人类文档更详细的地方？
   - Agent 有没有错误？

6. **输出评估结果**: 按照系统提示中的 JSON 格式输出最终评估

请开始评估。
"""

    # 构建 Agent
    print(f"\n🤖 初始化评估 Agent (model: {model})")
    try:
        agent = build_eval_agent(repo_path, report_dir, model)
    except Exception as e:
        print(f"❌ Agent 初始化失败: {e}", file=sys.stderr)
        return {"overall_score": 0, "error": f"Agent 初始化失败: {e}"}
    
    # 运行评估
    print(f"\n⏳ 正在运行评估 Agent...")
    print("-" * 40)
    
    inputs = {
        "messages": [
            SystemMessage(content=EVAL_SYSTEM_PROMPT),
            HumanMessage(content=eval_task),
        ]
    }
    
    final_response = ""
    step_count = 0
    
    try:
        for event in agent.stream(inputs, config={"recursion_limit": 50}):
            step_count += 1
            for node_name, state in event.items():
                messages = state.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    if isinstance(last_msg, AIMessage):
                        content = last_msg.content or ""
                        tool_calls = getattr(last_msg, "tool_calls", None) or []
                        
                        if tool_calls:
                            for tc in tool_calls:
                                if isinstance(tc, dict):
                                    tool_name = tc.get("name", "?")
                                    tool_args = tc.get("args", {})
                                else:
                                    tool_name = getattr(tc, "name", "?")
                                    tool_args = getattr(tc, "args", {})
                                
                                # 显示简短的工具调用信息
                                if "path" in tool_args or "file_path" in tool_args:
                                    path_arg = tool_args.get("path") or tool_args.get("file_path", "")
                                    short_path = os.path.basename(path_arg) if path_arg else "?"
                                    print(f"   🔧 {tool_name}({short_path})")
                                else:
                                    print(f"   🔧 {tool_name}(...)")
                        
                        if content and not tool_calls:
                            final_response = content
                            # 显示进度
                            preview = content[:100].replace("\n", " ")
                            if len(content) > 100:
                                preview += "..."
                            print(f"   📝 Agent 输出: {preview}")
    
    except Exception as e:
        print(f"\n❌ Agent 运行出错: {e}", file=sys.stderr)
        return {"overall_score": 0, "error": f"Agent 运行失败: {e}"}
    
    print("-" * 40)
    print(f"   完成，共 {step_count} 步")
    
    # 解析结果
    result = {}
    try:
        result = extract_json_from_response(final_response)
        print(f"\n✅ 成功解析评估结果")
    except Exception as e:
        print(f"\n⚠️  解析评估结果失败: {e}", file=sys.stderr)
        print(f"   原始响应长度: {len(final_response)} 字符")
        result = {
            "overall_score": 0,
            "dimension_scores": {},
            "highlights": [],
            "missing": [],
            "errors": [f"评估结果解析失败: {e}"],
            "summary": final_response[:500] if final_response else "无响应",
            "comparison_details": "",
        }
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"🎯 综合评分: {result.get('overall_score', 'N/A')}/100")
    print(f"{'='*60}")
    
    dim_scores = result.get("dimension_scores", {})
    if dim_scores:
        print("\n📊 分维度评分:")
        for dim, score in dim_scores.items():
            print(f"   {dim}: {score}")
    
    highlights = result.get("highlights", [])
    if highlights:
        print(f"\n✨ Agent 亮点 ({len(highlights)} 项):")
        for h in highlights[:3]:
            h_short = h[:80] + "..." if len(h) > 80 else h
            print(f"   • {h_short}")
    
    missing = result.get("missing", [])
    if missing:
        print(f"\n⚠️  缺失内容 ({len(missing)} 项):")
        for m in missing[:3]:
            m_short = m[:80] + "..." if len(m) > 80 else m
            print(f"   • {m_short}")
    
    # 生成评估报告
    eval_report = generate_evaluation_report(result, agent_report_path, repo_path)
    
    # 保存评估报告
    if output_path is None:
        output_path = os.path.join(report_dir, "evaluation.md")
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(eval_report)
        print(f"\n📄 评估报告已保存: {output_path}")
    except Exception as e:
        print(f"\n⚠️  保存评估报告失败: {e}", file=sys.stderr)
    
    # 保存 JSON
    json_path = output_path.replace(".md", ".json")
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"📄 评估数据已保存: {json_path}")
    except Exception as e:
        print(f"⚠️  保存 JSON 失败: {e}", file=sys.stderr)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="OS 分析报告评估程序 - 使用 Agent 对比报告与人类文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 评估指定报告
  python evaluate.py output/my-os/report.md repos/my-os
  
  # 指定输出路径
  python evaluate.py output/my-os/report.md repos/my-os -o eval_result.md
  
  # 使用不同模型
  python evaluate.py output/my-os/report.md repos/my-os --model gpt-4o

说明:
  评估程序会使用 Agent 自主探索仓库，查找并读取人类撰写的文档
  （如 README.md、设计文档、docs/ 目录等），与 Agent 生成的报告对比。
  
  评估维度包括：
  - coverage: 内容覆盖度
  - accuracy: 准确性
  - depth: 技术深度
  - structure: 结构完整性
  - citations: 证据引用
  
  输出:
  - evaluation.md: 评估报告（Markdown 格式）
  - evaluation.json: 评估数据（JSON 格式）
""",
    )
    
    parser.add_argument(
        "agent_report",
        help="Agent 生成的报告文件路径（如 output/my-os/report.md）",
    )
    parser.add_argument(
        "repo_path",
        help="仓库本地路径（如 repos/my-os）",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        help="评估报告输出路径（默认: 与 Agent 报告同目录的 evaluation.md）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"使用的 LLM 模型（默认从环境变量 MODEL_NAME 读取，或使用 {DEFAULT_MODEL}）",
    )
    
    args = parser.parse_args()
    
    result = run_evaluation(
        agent_report_path=args.agent_report,
        repo_path=args.repo_path,
        output_path=args.output_path,
        model=args.model,
    )
    
    # 返回退出码
    score = result.get("overall_score", 0)
    sys.exit(0 if score >= 60 else 1)


if __name__ == "__main__":
    main()
