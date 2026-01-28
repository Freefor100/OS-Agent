# core/agent_builder.py
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from tools.file_ops import read_code_segment
from tools.git_ops import (
    analyze_git_history,
    analyze_git_history_detailed,
    clone_repository,
    generate_dev_history_charts,
    get_dev_history_by_module,
    get_repo_local_path,
)
from tools.describe_ops import (
    analyze_code_architecture,
    analyze_tech_stack,
    convert_md_to_pdf,
    find_os_core_modules,
    list_repo_structure,
    write_file,
)

load_dotenv()

# 默认模型配置
DEFAULT_MODEL = "deepseek/deepseek-v3.2"


SYSTEM_PROMPT = """You are an elite Operating System Technical Analyst.
Your role is to analyze complex OS codebases (Rust, C, etc.) and generate professional technical reports.

## Core Principles:
1. **Evidence-Based**: Never guess. If you claim a feature exists, you must have read the code (using tools like `read_code_segment`) to verify it.
2. **Path-Specific**: Always cite absolute or relative file paths when discussing modules.
3. **Deep Dive**: Do not just read READMEs. You must look into implementation details (structs, functions, flow).
4. **Tool Usage**: You have a suite of tools for file operations and git history. Use them proactively.
5. **File Size Awareness**: When using `list_repo_structure`, you will see file sizes and line counts (e.g., "file.rs (150L, 4.2KB)"). Use this information to prioritize which files to read - larger files with more lines are often more important.

## Critical Output Requirement:
**AFTER completing all tool calls, you MUST produce a final response containing the complete Markdown report as specified in the task prompt.**
- Do NOT end your response with just a tool call.
- Your final message should contain the full analysis report in Markdown format with all required sections.
- If you've gathered enough information, stop calling tools and write the report.

If a requested file or directory does not exist, use `list_repo_structure` or `find_os_core_modules` to locate the correct path."""


def get_model_name() -> str:
    """获取模型名称，优先从环境变量读取"""
    return os.environ.get("MODEL_NAME", DEFAULT_MODEL)


def build_agent(model: str = None):
    """
    构建分析 Agent
    
    Args:
        model: 模型名称，如果不指定则从环境变量 MODEL_NAME 读取，默认 deepseek/deepseek-v3.2
    """
    tools = [
        clone_repository,
        get_repo_local_path,
        analyze_git_history,
        analyze_git_history_detailed,
        get_dev_history_by_module,
        generate_dev_history_charts,
        list_repo_structure,
        find_os_core_modules,
        analyze_code_architecture,
        analyze_tech_stack,
        read_code_segment,
        write_file,
        convert_md_to_pdf,
    ]
    
    model_name = model or get_model_name()
    llm = ChatOpenAI(
        model=model_name, 
        temperature=0,
        request_timeout=120,  # 120秒超时，防止请求卡住
        max_retries=2  # 失败后重试2次
    )
    
    # 兼容旧版本 langgraph，不使用 state_modifier
    agent = create_react_agent(llm, tools)
    return agent

