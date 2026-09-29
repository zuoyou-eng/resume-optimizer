"""统一诊断结果模型（《系统设计文档》4.2 —— 全系统最重要的数据契约）。

所有诊断模块（基础规范 / 内容质量 / ATS 适配 / 岗位匹配）必须输出此结构。
这一条同时解决三个问题（设计文档原文）：
  1. 报告整合简单 —— 报告层只面向一种结构编程；
  2. 模块可独立测试 —— 固定结构化输入进，期望 DiagnosisResult 出，无需数据库与服务（NFR-07）；
  3. 新增诊断维度无需改动报告层。

三个字段的设计意图直接服务于测试：
  evidence     让用户知道"凭什么这么说" → 测试可验证判定依据而非仅验证结论
  confidence   非确定性输出的显式表达 → 测试可按阈值断言，而非要求 100% 一致
  reproducible 直接对应 NFR-08 → 测试可断言该标记的正确性
"""
from dataclasses import dataclass, field, asdict
import hashlib

# 维度标识（与设计文档 4.2 dimension 字段对齐）
DIM_NORM = "norm"        # FR-04 基础规范体检
DIM_CONTENT = "content"  # FR-05 内容质量诊断
DIM_MACHINE = "machine"  # FR-06 ATS 适配体检
DIM_MATCH = "match"      # FR-08 岗位匹配度分析
DIM_STRUCTURE = "structure"  # FR-07 结构与篇幅体检（弹性项）

DIMENSION_LABELS = {
    DIM_NORM: "基础规范",
    DIM_CONTENT: "内容质量",
    DIM_MACHINE: "ATS 适配",
    DIM_MATCH: "岗位匹配",
    DIM_STRUCTURE: "结构与篇幅",
}

# 严重程度（设计文档 4.2）与对应扣分：分数 = 100 - Σ扣分，下限 0
SEVERITY_CRITICAL = "critical"
SEVERITY_MAJOR = "major"
SEVERITY_MINOR = "minor"
SEVERITY_INFO = "info"

SEVERITY_PENALTY = {
    SEVERITY_CRITICAL: 15,
    SEVERITY_MAJOR: 8,
    SEVERITY_MINOR: 3,
    SEVERITY_INFO: 0,
}

SEVERITY_ORDER = [SEVERITY_CRITICAL, SEVERITY_MAJOR, SEVERITY_MINOR, SEVERITY_INFO]

SEVERITY_LABELS = {
    SEVERITY_CRITICAL: "严重",
    SEVERITY_MAJOR: "重要",
    SEVERITY_MINOR: "次要",
    SEVERITY_INFO: "提示",
}


@dataclass
class Location:
    """定位信息（原则三：诊断必须给证据，必须能定位到具体语句）。"""

    field: str                 # 如 "experience[0].description" / "basic_info.phone"
    snippet: str = ""          # 原文片段
    offset: int = -1           # 位置偏移（-1 表示不适用/无法定位）


@dataclass
class Issue:
    """问题项：说明"哪里不对" + "缺什么" + "为什么这么判"。"""

    severity: str
    category: str
    location: Location
    problem: str
    suggestion: str
    evidence: str
    confidence: float = 1.0
    issue_id: str = ""

    def __post_init__(self) -> None:
        if not self.issue_id:
            self.issue_id = self._make_id()

    def _make_id(self) -> str:
        """确定性 ID：相同输入 → 相同 ID（NFR-08 可复现，也便于测试断言）。"""
        seed = "|".join(
            [
                self.severity,
                self.category,
                self.location.field,
                self.location.snippet,
                self.problem,
            ]
        )
        return "iss-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]

    def to_dict(self) -> dict:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity,
            "category": self.category,
            "location": asdict(self.location),
            "problem": self.problem,
            "suggestion": self.suggestion,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


@dataclass
class DiagnosisResult:
    """一个维度的一次诊断结论（设计文档 4.2 顶层结构）。"""

    resume_id: str
    dimension: str
    module_name: str
    score: int
    issues: list[Issue] = field(default_factory=list)
    rule_version: str = ""
    model_version: str | None = None
    elapsed_ms: float = 0.0
    reproducible: bool = True
    result_id: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.result_id:
            # 确定性 result_id：维度 + 规则版本 + 问题数，保证同输入同 ID
            seed = f"{self.resume_id}|{self.dimension}|{self.rule_version}|{len(self.issues)}"
            self.result_id = "dg-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        self.score = max(0, min(100, self.score))

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "resume_id": self.resume_id,
            "dimension": self.dimension,
            "module_name": self.module_name,
            "score": self.score,
            "issues": [i.to_dict() for i in self.issues],
            "meta": {
                "rule_version": self.rule_version,
                "model_version": self.model_version,
                "elapsed_ms": self.elapsed_ms,
                "reproducible": self.reproducible,
                **self.meta,
            },
        }


def compute_score(issues: list[Issue]) -> int:
    """按严重程度扣分计算维度得分（0-100）。

    规则集中写死，因此得分可被测试精确断言——这是"诊断可复现"的一部分。
    """
    penalty = sum(SEVERITY_PENALTY.get(i.severity, 0) for i in issues)
    return max(0, 100 - penalty)


def build_result(
    resume_id: str,
    dimension: str,
    module_name: str,
    issues: list[Issue],
    rule_version: str,
    elapsed_ms: float = 0.0,
    model_version: str | None = None,
    reproducible: bool = True,
    meta: dict | None = None,
    score: int | None = None,
) -> DiagnosisResult:
    """诊断模块的统一出口：只负责算分与打包，避免各模块重复实现计分逻辑。

    score 缺省时按严重程度扣分计算；**传入时优先使用**——岗位匹配维度（FR-08）
    的分数来自"要求覆盖率"而非问题扣分，两者是不同的计分语义，必须允许模块自带公式。
    """
    return DiagnosisResult(
        resume_id=resume_id,
        dimension=dimension,
        module_name=module_name,
        score=score if score is not None else compute_score(issues),
        issues=issues,
        rule_version=rule_version,
        model_version=model_version,
        elapsed_ms=elapsed_ms,
        reproducible=reproducible,
        meta=meta or {},
    )
