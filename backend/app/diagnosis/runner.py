"""诊断编排器：并行调用各诊断模块、整合综合报告（设计文档 5.1 / FR-10 / FR-11）。

两个关键的产品语义区分（实现时容易混淆）：
  1. **健康分 ≠ 匹配分**。健康分（FR-10）只汇总"简历本身好不好"的三个维度
     （基础规范 / 内容质量 / ATS 适配）；岗位匹配分（FR-08）是"这份简历与这个岗位
     合不合"，取决于岗位，不属于简历自身质量——两者分开呈现，避免误导用户。
  2. 问题清单按"影响大且好改 / 影响大难改 / 影响小"排序（FR-11），
     让用户从最容易见效的改动开始执行。
"""
import time

from app.diagnosis.base import DiagnosisContext
from app.diagnosis.models import (
    DIM_CONTENT,
    DIM_MACHINE,
    DIM_MATCH,
    DIM_NORM,
    DIM_STRUCTURE,
    SEVERITY_ORDER,
    SEVERITY_LABELS,
    DIMENSION_LABELS,
    DiagnosisResult,
    Issue,
)
from app.diagnosis import content, machine, match, norm, structure

# 模块注册表：新增诊断维度只需在此登记，报告层无需改动（设计文档原则一）
MODULES = {
    DIM_NORM: norm.MODULE,
    DIM_CONTENT: content.MODULE,
    DIM_MACHINE: machine.MODULE,
    DIM_MATCH: match.MODULE,
    DIM_STRUCTURE: structure.MODULE,
}

ALL_DIMENSIONS = list(MODULES.keys())

# 健康分权重（合计 1.0）：内容质量权重最高，ATS 适配是差异化亮点，基础规范是底线。
# 注意：structure（FR-07 结构与篇幅）与 match（FR-08 岗位匹配）都**不计入**健康分——
# 前者是弹性项，砍掉不应影响核心三维度的定义；后者的分数语义是"要求覆盖率"，
# 取决于岗位而非简历自身质量。两者在报告中单独呈现（counted_in_health=False）。
HEALTH_WEIGHTS = {
    DIM_NORM: 0.3,
    DIM_CONTENT: 0.4,
    DIM_MACHINE: 0.3,
}

# FR-11 排序依据：客观、可机械修正的问题归为"好改"；需要用户补充信息的归为"难改"
EASY_FIX_CATEGORIES = {
    "中英文标点混用",
    "日期格式不一致",
    "错别字",
    "时间线倒序",
    "无关个人信息",
    "ATS·装饰字符",
    "ATS·图标信息",
    "技能描述过长",
}

# 影响排序：0=影响大且好改，1=影响大难改，2=影响小
IMPACT_HIGH = 0
IMPACT_HARD = 1
IMPACT_LOW = 2


def run_diagnosis(
    resume_id: str,
    structure: dict,
    trace: list | None = None,
    unrecognized: list | None = None,
    dimensions: list[str] | None = None,
    jd: dict | None = None,
) -> list[DiagnosisResult]:
    """按维度执行诊断，返回各维度 DiagnosisResult 列表。

    维度缺省为全部五个；指定 dimensions 时只跑选中的（接口 4 支持"可指定维度"）。
    """
    dims = dimensions or ALL_DIMENSIONS
    unknown = [d for d in dims if d not in MODULES]
    if unknown:
        raise ValueError(f"未知诊断维度：{unknown}")
    # 岗位匹配必须以 JD 为比对基准；未提供 JD 时跳过该维度。
    # 过滤放在 runner 而非仅服务层，保证"模块独立调用"与"走接口"行为一致。
    if DIM_MATCH in dims and jd is None:
        dims = [d for d in dims if d != DIM_MATCH]

    results: list[DiagnosisResult] = []
    for dim in dims:
        module = MODULES[dim]
        ctx = DiagnosisContext(
            resume_id=resume_id,
            structure=structure or {},
            trace=trace or [],
            unrecognized=unrecognized or [],
            jd=jd,
        )
        results.append(module.diagnose(ctx))
    return results


def health_score(results: list[DiagnosisResult]) -> int:
    """FR-10 综合健康分：仅汇总 norm/content/machine 三维度（不含 match）。

    三维度权重固定，因此分数可被测试精确断言；某维度缺失时按剩余维度权重归一化。
    """
    scores = {r.dimension: r.score for r in results if r.dimension in HEALTH_WEIGHTS}
    if not scores:
        return 0
    total_weight = sum(HEALTH_WEIGHTS[d] for d in scores)
    weighted = sum(scores[d] * HEALTH_WEIGHTS[d] for d in scores)
    return round(weighted / total_weight)


def _impact_group(issue: Issue) -> int:
    if issue.severity in ("critical", "major"):
        return IMPACT_HIGH if issue.category in EASY_FIX_CATEGORIES else IMPACT_HARD
    return IMPACT_LOW


def sort_issues(issues: list[Issue]) -> list[Issue]:
    """FR-11：按"影响大且好改 / 影响大难改 / 影响小"排序，组内再按严重程度。

    稳定的确定性排序 → 同输入的清单顺序可复现（NFR-08）。
    """
    return sorted(
        issues,
        key=lambda i: (
            _impact_group(i),
            SEVERITY_ORDER.index(i.severity) if i.severity in SEVERITY_ORDER else 99,
            i.category,
        ),
    )


def build_report(resume_id: str, results: list[DiagnosisResult]) -> dict:
    """整合多个维度结果为综合报告（设计文档 4.1 报告整合模块）。"""
    all_issues: list[Issue] = []
    for r in results:
        all_issues.extend(r.issues)

    ordered = sort_issues(all_issues)

    dimension_scores: dict[str, dict] = {}
    for r in results:
        dimension_scores[r.dimension] = {
            "label": DIMENSION_LABELS.get(r.dimension, r.dimension),
            "score": r.score,
            "issue_count": len(r.issues),
            "module_name": r.module_name,
            "rule_version": r.rule_version,
            # 匹配分不计入健康分，单独标注语义
            "counted_in_health": r.dimension in HEALTH_WEIGHTS,
        }

    groups = {
        "high_impact_easy": [i for i in ordered if _impact_group(i) == IMPACT_HIGH],
        "high_impact_hard": [i for i in ordered if _impact_group(i) == IMPACT_HARD],
        "low_impact": [i for i in ordered if _impact_group(i) == IMPACT_LOW],
    }

    return {
        "resume_id": resume_id,
        "total_score": health_score(results),
        "dimension_scores": dimension_scores,
        "issue_summary": {
            "total": len(ordered),
            "by_severity": {
                sev: sum(1 for i in ordered if i.severity == sev)
                for sev in SEVERITY_ORDER
            },
            "groups": {
                "high_impact_easy": [_issue_brief(i) for i in groups["high_impact_easy"]],
                "high_impact_hard": [_issue_brief(i) for i in groups["high_impact_hard"]],
                "low_impact": [_issue_brief(i) for i in groups["low_impact"]],
            },
        },
        "issues": [
            {**i.to_dict(), "severity_label": SEVERITY_LABELS.get(i.severity, i.severity)}
            for i in ordered
        ],
        "reproducible": all(r.reproducible for r in results),
    }


def _issue_brief(issue: Issue) -> dict:
    """问题清单中的简要条目（定位 + 结论 + 建议），完整证据在 issues 中。"""
    return {
        "issue_id": issue.issue_id,
        "severity": issue.severity,
        "severity_label": SEVERITY_LABELS.get(issue.severity, issue.severity),
        "category": issue.category,
        "field": issue.location.field,
        "snippet": issue.location.snippet,
        "problem": issue.problem,
        "suggestion": issue.suggestion,
    }


def total_elapsed_ms(results: list[DiagnosisResult]) -> float:
    return round(sum(r.elapsed_ms for r in results), 1)


def now_ms() -> float:
    return round(time.perf_counter() * 1000, 1)
