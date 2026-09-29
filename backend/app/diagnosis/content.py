"""FR-05 内容质量诊断模块。

逐条诊断经历描述（需求原文）：
  要素完整性（做了什么 / 怎么做 / 结果如何）、量化结果、表达力度、空话套话、注水嫌疑。

设计原则三的落地：每条结论都携带 location（定位到具体条目）与 evidence
（命中了哪条规则 / 哪个信号词），使判定过程可被测试直接断言。
"""
import time

from app.diagnosis.base import DiagnosisContext, DiagnosisModule
from app.diagnosis.models import (
    DIM_CONTENT,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    DiagnosisResult,
    Issue,
    Location,
    build_result,
)
from app.diagnosis import rules

RULE_VERSION = "content-1.0.0"

# 参与内容诊断的条目段：(结构键, 中文名)
_DESC_SECTIONS = [("experience", "实习经历"), ("projects", "项目经历")]

# 注水嫌疑阈值：描述足够长却没有任何数字 → 信息密度低
_WORDY_LENGTH = 120


def _has_any(text: str, keywords: list[str]) -> str | None:
    """返回首个命中的关键词，用于 evidence 说明"凭什么这么判"。"""
    for kw in keywords:
        if kw in text:
            return kw
    return None


class ContentModule(DiagnosisModule):
    """内容质量诊断（FR-05）。"""

    dimension = DIM_CONTENT
    module_name = "content_quality"
    rule_version = RULE_VERSION

    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        start = time.perf_counter()
        structure = ctx.structure or {}
        issues: list[Issue] = []

        for section, label in _DESC_SECTIONS:
            for idx, item in enumerate(structure.get(section) or []):
                issues.extend(self._check_item(section, label, idx, item or {}))

        issues.extend(self._check_skills_quality(structure))

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return build_result(
            resume_id=ctx.resume_id,
            dimension=self.dimension,
            module_name=self.module_name,
            issues=issues,
            rule_version=self.rule_version,
            elapsed_ms=elapsed,
            reproducible=True,
            meta={"sections": [s for s, _ in _DESC_SECTIONS]},
        )

    # ---------- 单条经历的三要素诊断 ----------
    def _check_item(
        self, section: str, label: str, idx: int, item: dict
    ) -> list[Issue]:
        issues: list[Issue] = []
        desc = (item.get("description") or "").strip()
        field_path = f"{section}[{idx}].description"
        loc = Location(field=field_path, snippet=desc[:80])

        if not desc:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="描述缺失",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条没有任何描述",
                    suggestion="请至少写清楚：做了什么 / 用了什么方法 / 结果如何",
                    evidence="该条目 description 为空",
                )
            )
            return issues

        if len(desc) < rules.MIN_DESC_LENGTH:
            # 过短描述已在 FR-04 报过"描述过于简略"，此处不重复扣分，仅给提示
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="描述过于简略",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条描述仅 {len(desc)} 字",
                    suggestion="建议按「动作 + 方法 + 结果」扩写到 2-3 句",
                    evidence=f"描述长度 {len(desc)} < 阈值 {rules.MIN_DESC_LENGTH}",
                )
            )
            return issues

        # 要素一：做了什么
        action = _has_any(desc, rules.ACTION_SIGNALS)
        if not action:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="要素缺失·做了什么",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条看不出你具体做了什么",
                    suggestion="用一个明确的动作开头（如：设计 / 开发 / 搭建 / 优化），说明你负责的范围",
                    evidence="描述中未命中任何动作信号词",
                )
            )

        # 要素二：怎么做
        method = _has_any(desc, rules.METHOD_SIGNALS)
        if not method:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="要素缺失·怎么做",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条没有说明实现方式",
                    suggestion="补充你使用的技术、工具或方法（如：基于 Python 编写自动化脚本）",
                    evidence="描述中未命中任何方法信号词",
                )
            )

        # 要素三：结果如何（结果词或任一数字均可作为结果证据）
        result = _has_any(desc, rules.RESULT_SIGNALS)
        has_quant = bool(rules.QUANT_RE.search(desc))
        if not result and not has_quant:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="要素缺失·结果如何",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条没有交代结果",
                    suggestion="补充产出或影响（如：覆盖 X 个场景 / 节省 X 小时 / 通过 X 项验收）",
                    evidence="描述中既无结果导向词，也无任何数字",
                )
            )

        # 量化结果
        if not has_quant:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="缺少量化结果",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条没有任何可量化数据",
                    suggestion="能定量的尽量定量（数量 / 比例 / 耗时 / 规模）；确实无法定量时，写清产出物",
                    evidence="描述中未匹配到数字或数量单位",
                )
            )

        # 表达力度弱
        weak = _has_any(desc, rules.WEAK_PHRASES)
        if weak:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="表达力度弱",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条使用了弱参与表述「{weak}」",
                    suggestion="改成你实际承担的动作；若确实只是参与，就写清你负责的那一部分",
                    evidence=f"命中弱表达词：{weak}",
                )
            )

        # 空话套话
        cliche = _has_any(desc, rules.CLICHE_PHRASES)
        if cliche:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="空话套话",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条含空话套话「{cliche}」",
                    suggestion="删除该表述，用一件具体的事例替代（谁 + 什么场景 + 你做了什么 + 结果）",
                    evidence=f"命中套话词表：{cliche}",
                )
            )

        # 注水嫌疑：够长却零数字
        if len(desc) >= _WORDY_LENGTH and not has_quant:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="注水嫌疑",
                    location=loc,
                    problem=f"{label}第 {idx + 1} 条长达 {len(desc)} 字却不含任何数据",
                    suggestion="压缩修饰性语句，保留事实与数字；长而空不如短而实",
                    evidence=f"长度 {len(desc)} ≥ {_WORDY_LENGTH} 且无数字",
                )
            )
        return issues

    # ---------- 技能列表质量 ----------
    def _check_skills_quality(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        skills = structure.get("skills") or []

        if not skills:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="技能缺失",
                    location=Location(field="skills", snippet=""),
                    problem="未解析到任何技能条目",
                    suggestion="请单列「专业技能」区块，逐条列出你掌握的语言、框架与工具",
                    evidence="结构化结果 skills 为空",
                )
            )
        elif len(skills) < 3:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="技能条目偏少",
                    location=Location(field="skills", snippet="、".join(skills)[:60]),
                    problem=f"仅解析到 {len(skills)} 条技能",
                    suggestion="可补充与目标岗位相关的语言、框架、工具与测试方法",
                    evidence=f"技能条目数 {len(skills)} < 3",
                )
            )

        for idx, skill in enumerate(skills):
            if len(skill) > 30:
                issues.append(
                    Issue(
                        severity=SEVERITY_MINOR,
                        category="技能描述过长",
                        location=Location(field=f"skills[{idx}]", snippet=skill[:60]),
                        problem=f"技能第 {idx + 1} 条长达 {len(skill)} 字，不像一个技能点",
                        suggestion="请拆成多条短技能，一条只讲一个技能",
                        evidence=f"长度 {len(skill)} > 30",
                    )
                )
        return issues


MODULE = ContentModule()
