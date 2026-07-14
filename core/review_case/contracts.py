from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    section: str = ""
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "section": self.section,
            "message": self.message,
        }

    def format(self) -> str:
        loc = self.path
        if self.section:
            loc = f"{loc}#{self.section}" if loc else self.section
        return f"{self.severity.upper()} {self.code}: {loc}: {self.message}" if loc else f"{self.severity.upper()} {self.code}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add(self, code: str, message: str, path: str | Path = "", section: str = "", severity: str = "error") -> None:
        self.issues.append(ValidationIssue(code=code, message=message, path=str(path), section=section, severity=severity))

    def extend(self, other: "ValidationReport | list[ValidationIssue]") -> None:
        if isinstance(other, ValidationReport):
            self.issues.extend(other.issues)
        else:
            self.issues.extend(other)

    def raise_for_errors(self) -> None:
        if not self.ok:
            raise ReviewCaseValidationError(self)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [issue.as_dict() for issue in self.issues]}

    def format(self) -> str:
        if not self.issues:
            return "OK"
        return "\n".join(issue.format() for issue in self.issues)


class ReviewCaseValidationError(RuntimeError):
    def __init__(self, report: ValidationReport):
        super().__init__(report.format())
        self.report = report


REQUIRED_BASE_HEADINGS = [
    "选中 Base",
    "证据覆盖",
    "未选候选",
    "方向判断",
    "Base 之后需要描述的模块",
]

REQUIRED_MODULE_HEADINGS = [
    "适用范围",
    "实现内容",
    "相对 Base 的变化",
    "真实工作量判断",
    "继承、外部依赖与缺失",
    "文档声明复核",
    "证据",
]

REQUIRED_CHEAT_HEADINGS = [
    "测试输出伪造",
    "测试名或 argv 特判",
    "syscall/exec 特判",
    "runner 或桥接层绕过",
    "成功存根、假对象与硬编码伪装",
    "Prompt Injection",
    "结论",
]

REQUIRED_DOC_CLAIM_HEADINGS = [
    "声明与代码一致",
    "声明夸大或不实",
    "待补证声明",
]

REQUIRED_HISTORY_AI_HEADINGS = [
    "提交时间线",
    "AI 使用证据",
    "批量导入与生成痕迹",
    "结论",
]

REQUIRED_CONTRADICTION_HEADINGS = [
    "冲突清单",
    "仲裁结果",
    "待补事实",
]

REQUIRED_REPORT_HEADINGS = [
    "整体结论",
    "重点结论",
    "真实工作量分层",
    "Base、其他来源与同届传播关系",
    "内核架构图",
    "模块实现细节及 Base 差异",
    "证据索引",
]

OPTIONAL_REPORT_HEADINGS = [
    "文档声明审查",
    "开发历史与 AI 使用",
    "测评异常与提示注入风险",
]

VALID_MODULE_STATUS = {"implemented", "partial", "minimal", "absent"}
VALID_ORIGINALITY = {"novel", "adapted_major", "adapted_minor", "inherited", "external", "uncertain"}
VALID_BASE_DELTA = {"major", "minor", "none", "unclear"}
VALID_BASE_CONFIDENCE = {"high", "medium", "low"}
VALID_FINDING_STATUS = {"findings", "no_findings"}
VALID_CONTRADICTION_STATUS = {"none", "unresolved", "resolved"}
