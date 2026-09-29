"""诊断模块抽象接口（设计文档 4.1 原则一/原则二 + NFR-07 模块解耦）。

每个诊断模块实现同一接口：吃结构化简历数据，吐统一 DiagnosisResult。
模块之间互不依赖、不访问数据库、不依赖服务层——因此可以脱离主流程单独测试。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.diagnosis.models import DiagnosisResult


@dataclass
class DiagnosisContext:
    """诊断输入上下文。

    structure 即 FR-02 的结构化结果（dict 形式），trace 为解析轨迹，
    unrecognized 为未识别内容（FR-03）——ATS 模块需要它来判断"哪些原文机器没读到"。
    jd 仅在岗位匹配维度传入：{id, title, raw_text, extracted_keys}。
    """

    resume_id: str
    structure: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    unrecognized: list = field(default_factory=list)
    jd: dict | None = None


class DiagnosisModule(ABC):
    """诊断模块基类：固定 rule_version 使结论可复现、可回归（NFR-08）。"""

    dimension: str = ""
    module_name: str = ""
    rule_version: str = ""

    @abstractmethod
    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        """执行诊断，返回统一诊断结果。实现必须是纯函数式：不写库、不读外部状态。"""
        raise NotImplementedError
