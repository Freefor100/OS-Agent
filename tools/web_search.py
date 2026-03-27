import json
import os
import urllib.error
import urllib.parse
import urllib.request

from langchain.tools import tool


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def _search_tavily(query: str, max_results: int = 5) -> str:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return ""
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
    }
    data = _post_json(
        "https://api.tavily.com/search",
        headers={"Content-Type": "application/json"},
        payload=payload,
    )
    results = []
    for item in data.get("results", [])[:max_results]:
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        snippet = (item.get("content", "") or "").strip().replace("\n", " ")
        results.append(f"- {title}\n  URL: {url}\n  摘要: {snippet[:220]}")
    return "\n".join(results)


def _search_serper(query: str, max_results: int = 5) -> str:
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return ""
    payload = {"q": query, "num": max_results}
    data = _post_json(
        "https://google.serper.dev/search",
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
        },
        payload=payload,
    )
    results = []
    for item in data.get("organic", [])[:max_results]:
        title = item.get("title", "Untitled")
        url = item.get("link", "")
        snippet = (item.get("snippet", "") or "").strip().replace("\n", " ")
        results.append(f"- {title}\n  URL: {url}\n  摘要: {snippet[:220]}")
    return "\n".join(results)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """查询比赛背景、赛道定位、公开技术背景或 OS 架构常识。禁止用它判断仓库实现事实或源码相似度。"""
    if not os.environ.get("ENABLE_WEB_SEARCH", "false").strip().lower() in {"1", "true", "yes", "on"}:
        return "web_search 已禁用。若要启用，请设置 ENABLE_WEB_SEARCH=true，并提供 TAVILY_API_KEY 或 SERPER_API_KEY。"

    allowed_hint = (
        "仅允许查询全国大学生操作系统比赛背景、赛道目标、功能要求、公开技术背景或 OS 架构常识；"
        "禁止把搜索结果当作仓库实现证据。"
    )
    providers = [
        ("tavily", _search_tavily),
        ("serper", _search_serper),
    ]
    errors = []
    for provider_name, provider in providers:
        try:
            result = provider(query=query, max_results=max_results)
            if result.strip():
                return f"[provider={provider_name}]\n{allowed_hint}\n{result}"
        except urllib.error.URLError as exc:
            errors.append(f"{provider_name}: {exc}")
        except Exception as exc:
            errors.append(f"{provider_name}: {exc}")

    return (
        f"web_search 未获得可用结果。\n"
        f"{allowed_hint}\n"
        f"已尝试 provider: {', '.join(name for name, _ in providers)}\n"
        f"错误: {'; '.join(errors) if errors else '未配置可用 provider'}"
    )
