# evaluate.py
"""
OS 分析报告评估程序 (按章节切分评估版)

工作原理：
1. 扫描 `output/<os>/sections/` 目录下的所有分段报告。
2. 对每个章节（如"内存管理"）启动一个独立的 Agent：
   - Agent 只读取该章节的报告内容。
   - Agent 使用关键词（如"memory", "mm"）在仓库中搜索对应的人类文档。
   - Agent 仅针对该领域进行评分（覆盖度、准确性等）。
3. 最后汇总所有章节的评分，生成总评估报告。

优点：
- 注意力集中：Agent 不会被无关内容干扰。
- 覆盖率高：强制覆盖所有章节。
- 记忆隔离：每个章节评估使用全新的上下文。
"""

import argparse
import json
import os
import sys
import glob
import re
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

# ============================================================
# 配置与常量
# ============================================================

# 默认模型
DEFAULT_MODEL = os.environ.get("MODEL_NAME", "deepseek/deepseek-v3.2")

# 评估维度
EVALUATION_DIMENSIONS = {
    "coverage": "内容覆盖度 - Agent 报告覆盖了人类文档中多少关键技术点",
    "accuracy": "准确性 - Agent 的技术描述与人类文档是否一致",
    "depth": "技术深度 - Agent 是否深入到代码/实现层面",
    "citations": "证据引用 - 是否引用了具体的文件路径/代码片段"
}

# 章节关键词映射（用于引导 Agent 搜索人类文档）
SECTION_KEYWORDS = {
    "启动": ["boot", "init", "startup", "entry", "arch"],
    "内存": ["mm", "memory", "paging", "heap", "alloc"],
    "进程": ["process", "task", "thread", "scheduler", "sched"],
    "中断": ["interrupt", "irq", "trap", "exception", "handler"],
    "文件": ["fs", "filesystem", "file", "vfs"],
    "设备": ["driver", "device", "hal", "bsp"],
    "同步": ["sync", "mutex", "lock", "atomic"],
    "多核": ["smp", "multicore", "hart", "cpu"],
    "网络": ["net", "network", "tcp", "ip", "socket"],
    "安全": ["security", "permission", "user", "access"],
}

# ============================================================
# 工具定义
# ============================================================

def _is_path_allowed(path: str, allowed_roots: list[str]) -> bool:
    abs_path = os.path.abspath(path)
    for root in allowed_roots:
        abs_root = os.path.abspath(root)
        if abs_path.startswith(abs_root):
            return True
    return False

def create_restricted_tools(repo_path: str, output_path: str):
    """创建受限的文件操作工具"""
    allowed_roots = [
        os.path.abspath(repo_path),
        os.path.abspath(output_path)
    ]
    
    @tool
    def list_directory(path: str, max_depth: int = 2) -> str:
        """列出目录结构。"""
        if not _is_path_allowed(path, allowed_roots):
            return f"❌ 错误：不允许访问路径 '{path}'。"
        if not os.path.isdir(path):
            return f"❌ 错误：'{path}' 不是有效目录。"
        
        try:
            items = os.listdir(path)
            items = [i for i in items if i not in {".git", "__pycache__", "target", "node_modules", ".venv", "deps"}]
            items.sort()
            result = []
            for item in items[:50]:
                full = os.path.join(path, item)
                if os.path.isdir(full):
                    result.append(f"{item}/")
                else:
                    result.append(item)
            if len(items) > 50:
                result.append(f"... (共 {len(items)} 项)")
            return "\n".join(result)
        except Exception as e:
            return f"Error: {e}"

    @tool
    def find_documents(path: str, keywords: str) -> str:
        """
        在指定目录下搜索文档文件。
        会返回：
        1. 匹配关键词 (.md, .txt, .rst, .doc) 的文件
        2. 所有的 PDF 文件 (通常是参赛文档)
        3. 根目录下的 README 或 Design 文档
        
        Args:
            path: 搜索根目录
            keywords: 关键词，用空格分隔，如 "memory mm paging"
        """
        if not _is_path_allowed(path, allowed_roots):
            return f"❌ 错误：不允许访问路径 '{path}'。"
            
        kw_list = keywords.lower().split()
        found = []
        # 普通文档后缀
        text_exts = {".md", ".txt", ".rst", ".doc", ".docx"}
        # 全局重要文档 (PDF通常包含完整内容)
        global_exts = {".pdf"} 
        
        for root, _, files in os.walk(path):
            if ".git" in root or "node_modules" in root or "target" in root: continue
            
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                f_lower = f.lower()
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, path)
                
                # 1. 总是包含 PDF (极大概率是参赛文档)
                if ext in global_exts:
                    found.append(f"[Global/PDF] {rel_path}")
                    continue
                    
                # 2. 总是包含 README / DESIGN
                if f_lower in ["readme.md", "design.md", "documentation.md", "guide.md"]:
                    found.append(f"[Global/Doc] {rel_path}")
                    continue
                
                # 3. 关键词匹配其他文本文件
                if ext in text_exts:
                    if any(k in f_lower for k in kw_list):
                        found.append(f"[Match] {rel_path}")
                    
        if not found:
            return "未找到相关文档 (无 PDF, README 或 关键词匹配文件)。"
        
        # 去重并排序 (让 Global 排在前面)
        found = sorted(list(set(found)), key=lambda x: (not x.startswith("[Global"), x))
        return "\n".join(found[:30])

    @tool
    def read_file(file_path: str, max_chars: int = 50000) -> str:
        """读取文件内容 (支持 .md, .txt, .pdf 等)。"""
        if not _is_path_allowed(file_path, allowed_roots):
            return f"❌ 错误：不允许访问文件 '{file_path}'。"
        
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            # PDF 处理
            if ext == ".pdf":
                try:
                    import PyPDF2
                    text_content = []
                    with open(file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        # 限制页数以防过大，或读取全部
                        # 考虑到 Context Window，读取前 50 页或 全部
                        max_pages = 50 
                        num_pages = len(reader.pages)
                        read_limit = min(num_pages, max_pages)
                        
                        text_content.append(f"--- PDF Content (Pages 1-{read_limit} of {num_pages}) ---")
                        for i in range(read_limit):
                            page_text = reader.pages[i].extract_text()
                            if page_text:
                                text_content.append(page_text)
                                
                    content = "\n".join(text_content)
                except ImportError:
                    return "❌ 错误: 未安装 PyPDF2 库，无法读取 PDF。请告知用户安装。"
                except Exception as e:
                    return f"❌ 读取 PDF 失败: {e}"
            else:
                # 普通文本处理
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

            if len(content) > max_chars:
                return content[:max_chars] + f"\n\n... [已截断，原文共 {len(content)} 字符]"
            return content
        except Exception as e:
            return f"Error: {e}"

    return [list_directory, find_documents, read_file]

# ============================================================
# Section Evaluator
# ============================================================

class SectionEvaluator:
    def __init__(self, repo_path: str, output_path: str, model_name: str):
        self.repo_path = repo_path
        self.output_path = output_path
        self.model_name = model_name
        self.tools = create_restricted_tools(repo_path, output_path)
        
    def evaluate_section(self, section_file: str) -> Dict[str, Any]:
        """评估单个章节"""
        section_name = os.path.basename(section_file)
        print(f"\nEvaluating section: {section_name}")
        
        # 1. 确定关键词
        keywords = ["os", "kernel", "design"]
        for key, vals in SECTION_KEYWORDS.items():
            if key in section_name:
                keywords.extend(vals)
                break
        kw_str = " ".join(keywords)
        
        # 2. 构建 Agent
        llm = ChatOpenAI(model=self.model_name, temperature=0)
        agent = create_react_agent(llm, self.tools)
        
        # 3. 构建 Prompt (以人类文档为基准 - Ground Truth Approach)
        prompt = f"""
你是一个严格的 OS 评分员。你的目标是对比【人类写的原始文档】和【Agent 生成的分析报告】，以人类文档为标准答案，给 Agent 的报告打分。

## 评估目标章节：{section_name}
（关键词提示：{kw_str}）

## 你的工作流程（必须严格遵守）
1.  **第一步：确立标准答案（Ground Truth）**
    - 使用 `find_documents` 和 `read_file` 找到并阅读仓库里的人类核心文档（优先看 PDF、README、Design 文档）。
    - *切记*：如果存在全篇的 PDF/MD 文档，请务必读取它（通常包含所有章节）。
    - 从人类文档中提炼出关于【{section_name}】这一模块的所有关键设计点、算法名称、文件结构描述。

2.  **第二步：批改试卷（Verify）**
    - 读取 Agent 生成的章节报告：`{section_file}`
    - 检查 Agent 的报告是否准确复述了人类文档中的设计点。

3.  **第三步：打分与对比**
    - 评分的核心标准是：**Agent 报告与人类文档的接近程度 (Closeness)**。
    - 如果人类文档提到了某个特性（如 Slab 分配器），但 Agent没写 -> 扣分（覆盖率不足）。
    - 如果人类文档没提，但 Agent 瞎编了 -> 扣分（准确性不足）。
    - 如果人类文档很简略，但 Agent 通过代码分析补充了细节 -> 加分（深度）。

## 评分维度 (0-100)
- **metrics**: 接近度 (Closeness) - 内容与人类文档的重合度。
- **accuracy**: 准确性 - 是否没有事实错误。
- **depth**: 深度 - 是否在人类文档基础上挖掘了代码细节。

## 输出格式
请输出如下 JSON：
```json
{{
    "score": <0-100 总分>,
    "dimensions": {{ "metrics": <分>, "accuracy": <分>, "depth": <分> }},
    "ground_truth_points": ["<人类文档提到的关键点1>", "<人类文档提到的关键点2>"],
    "highlights": ["<Agent分析对的地方/亮点>"],
    "missing": ["<人类有但Agent没写的点1>", "<人类有但Agent没写的点2>"],
    "errors": ["<错误描述>"],
    "summary": "<评价总结>"
}}
```
"""
        # 4. 运行 Agent
        inputs = {"messages": [HumanMessage(content=prompt)]}
        final_state = agent.invoke(inputs, config={"recursion_limit": 20})
        
        # 5. 提取结果
        last_msg = final_state["messages"][-1].content
        try:
            return self._parse_json(last_msg)
        except Exception as e:
            print(f"❌ 解析 {section_name} 结果失败: {e}")
            return {"score": 0, "error": str(e), "summary": "解析失败"}
            
    def _parse_json(self, text: str) -> dict:
        """简单的 JSON 提取器"""
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            return json.loads(text[start:end].strip())
        if "{" in text: # 尝试直接寻找大括号
             s = text.find("{")
             e = text.rfind("}") + 1
             return json.loads(text[s:e])
        return {}

# ============================================================
# 主流程
# ============================================================

def run_evaluation(report_path: str, repo_path: str, output_file: str = None, model: str = None):
    print(f"🚀 开始按章节评估 OS-Agent 报告")
    print(f"📄 报告基准: {report_path}")
    print(f"📁 仓库路径: {repo_path}")
    
    # 1. 找到所有 sections
    report_dir = os.path.dirname(report_path)
    sections_dir = os.path.join(report_dir, "sections")
    
    if not os.path.isdir(sections_dir):
        print(f"❌ 未找到 sections 目录: {sections_dir}")
        return
        
    sections = sorted(glob.glob(os.path.join(sections_dir, "*.md")))
    if not sections:
        print(f"❌ sections 目录为空")
        return
        
    print(f"📚 发现 {len(sections)} 个章节文件，将逐一评估...")
    
    evaluator = SectionEvaluator(repo_path, report_dir, model or DEFAULT_MODEL)
    results = {}
    total_score = 0
    
    # 2. 循环评估每个 section
    eval_details = []
    
    for sec in sections:
        sec_name = os.path.basename(sec)
        # 忽略非内容章节
        if "概览" in sec_name or "摘要" in sec_name:
            continue
            
        print(f"{'-'*40}")
        res = evaluator.evaluate_section(sec)
        results[sec_name] = res
        
        s = res.get("score", 0)
        total_score += s
        print(f"   ✅ {sec_name}: {s} 分")
        print(f"      {res.get('summary', '')[:50]}...")
        
        # 记录详情用于生成报告
        eval_details.append(f"""
### {sec_name} (评分: {s})
- **维度**: {res.get('dimensions', {})}
- **亮点**: {', '.join(res.get('highlights', []))}
- **缺失**: {', '.join(res.get('missing', []))}
- **评价**: {res.get('summary')}
""")

    # 3. 计算最终得分
    count = len(results)
    avg_score = round(total_score / count, 1) if count > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"🎯 综合评分: {avg_score} / 100")
    print(f"{'='*60}")
    
    # 4. 生成汇总报告
    final_report = f"""# 📊 OS-Agent 深度评估报告 (按章节)

**综合评分**: {avg_score}
**评估时间**: {datetime.now()}
**评估模块数**: {count}

---
## 分章节评估详情
{''.join(eval_details)}

---
*本报告由 Multi-Agent 分章节评估生成*
"""
    
    if not output_file:
        output_file = os.path.join(report_dir, "evaluation.md")
        
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_report)
    print(f"📄 评估报告已保存至: {output_file}")
    
    # 保存 JSON 数据
    json_path = output_file.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def main():
    parser = argparse.ArgumentParser(description="分章节评估 OS-Agent 报告")
    parser.add_argument("report_path", help="Agent 报告路径 (eg: output/os/report.md)")
    parser.add_argument("repo_path", help="OS 仓库路径 (eg: repos/os)")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("--model", help="LLM 模型名称")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.report_path):
        print("❌ 报告文件不存在")
        sys.exit(1)
        
    run_evaluation(args.report_path, args.repo_path, args.output, args.model)

if __name__ == "__main__":
    main()
