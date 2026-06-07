"""
错误处理模块

错误分类、重试策略与错误追踪（Describe / RAG 等链路共用）。
"""
import json
import logging
import traceback
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional


class ErrorType(Enum):
    """错误类型枚举"""
    NETWORK_ERROR = "网络错误"
    API_ERROR = "API错误"
    TIMEOUT_ERROR = "超时错误"
    PARSE_ERROR = "解析错误"
    VALIDATION_ERROR = "验证错误"
    TOOL_ERROR = "工具执行错误"
    UNKNOWN_ERROR = "未知错误"


class RetryConfig:
    """重试配置"""
    MAX_RETRIES = 3  # 最大重试次数
    INITIAL_BACKOFF = 2  # 初始退避时间（秒）
    MAX_BACKOFF = 60  # 最大退避时间（秒）
    BACKOFF_MULTIPLIER = 2  # 退避倍数

    # 不同错误类型的重试策略
    RETRYABLE_ERRORS = {
        ErrorType.NETWORK_ERROR: True,
        ErrorType.API_ERROR: True,
        ErrorType.TIMEOUT_ERROR: True,
        ErrorType.PARSE_ERROR: False,  # 解析错误重试无意义
        ErrorType.VALIDATION_ERROR: False,
        ErrorType.TOOL_ERROR: True,
        ErrorType.UNKNOWN_ERROR: True,
    }


def classify_error(exception: Exception) -> ErrorType:
    """分类异常类型"""
    error_msg = str(exception).lower()
    error_type_name = type(exception).__name__.lower()

    # 超时错误（优先于网络错误，避免 APITimeoutError 被误判为网络错误）
    if "timeout" in error_msg or "timeout" in error_type_name:
        return ErrorType.TIMEOUT_ERROR

    # 网络相关错误
    if any(keyword in error_msg for keyword in ["connection", "network", "socket", "dns"]):
        return ErrorType.NETWORK_ERROR
    if any(keyword in error_type_name for keyword in ["connection", "timeout", "socket"]):
        return ErrorType.NETWORK_ERROR

    # API 错误
    if any(keyword in error_msg for keyword in ["api", "rate limit", "quota", "429", "503"]):
        return ErrorType.API_ERROR
    if "openai" in error_type_name or "api" in error_type_name:
        return ErrorType.API_ERROR

    # JSON 解析错误
    if "json" in error_msg or "json" in error_type_name:
        return ErrorType.PARSE_ERROR

    # 工具执行错误
    if "tool" in error_msg:
        return ErrorType.TOOL_ERROR

    return ErrorType.UNKNOWN_ERROR


def calculate_backoff(retry_count: int) -> int:
    """计算退避时间（指数退避）"""
    backoff = RetryConfig.INITIAL_BACKOFF * (RetryConfig.BACKOFF_MULTIPLIER ** retry_count)
    return min(backoff, RetryConfig.MAX_BACKOFF)


class ErrorTracker:
    """错误追踪器"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.errors = []
        self.error_stats = {error_type: 0 for error_type in ErrorType}

    def record_error(
        self,
        section_name: str,
        error_type: ErrorType,
        exception: Exception,
        retry_count: int,
        context: Dict[str, Any] = None
    ):
        """记录错误信息"""
        error_record = {
            "timestamp": datetime.now().isoformat(),
            "section": section_name,
            "error_type": error_type.value,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "traceback": traceback.format_exc(),
            "retry_count": retry_count,
            "context": context or {}
        }

        self.errors.append(error_record)
        self.error_stats[error_type] += 1

        # 记录到日志
        logging.error(
            f"[{section_name}] {error_type.value} (重试: {retry_count}): "
            f"{type(exception).__name__}: {exception}"
        )
        logging.debug(f"错误堆栈:\n{error_record['traceback']}")

    def save_error_report(self, filename: str = "error_report.json"):
        """保存错误报告"""
        if not self.errors:
            return

        import os
        error_report_path = os.path.join(self.output_dir, filename)
        try:
            with open(error_report_path, "w", encoding="utf-8") as f:
                json.dump({
                    "total_errors": len(self.errors),
                    "error_statistics": {k.value: v for k, v in self.error_stats.items()},
                    "errors": self.errors
                }, f, ensure_ascii=False, indent=2)

            logging.info(f"错误报告已保存: {error_report_path}")
            print(f"📋 错误报告已保存: {error_report_path}")
        except Exception as e:
            logging.error(f"保存错误报告失败: {e}")

    def generate_error_summary(self) -> str:
        """生成错误摘要（Markdown格式）"""
        if not self.errors:
            return "## 错误统计\n\n✅ 无错误发生\n"

        lines = [
            "## 错误统计",
            "",
            f"- **总错误数**: {len(self.errors)}",
            ""
        ]

        # 按错误类型统计
        lines.append("### 错误类型分布")
        lines.append("")
        for error_type, count in self.error_stats.items():
            if count > 0:
                lines.append(f"- **{error_type.value}**: {count} 次")

        lines.append("")
        lines.append("### 详细错误列表")
        lines.append("")

        for i, error in enumerate(self.errors, 1):
            lines.append(f"#### 错误 {i}: {error['section']}")
            lines.append(f"- **类型**: {error['error_type']}")
            lines.append(f"- **异常**: {error['exception_type']}")
            lines.append(f"- **消息**: {error['exception_message']}")
            lines.append(f"- **重试次数**: {error['retry_count']}")
            lines.append(f"- **时间**: {error['timestamp']}")
            lines.append("")

        return "\n".join(lines)
