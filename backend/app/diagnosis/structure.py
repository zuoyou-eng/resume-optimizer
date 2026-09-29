"""FR-07 结构与篇幅体检模块（弹性项，V1.2）。

检查项（与需求文档表格逐条对应）：
  模块完整性 / 页数与身份匹配度 / 篇幅占比 / 关键信息位置。

三项设计决策（影响可复现性与误报率，均有测试固化）：

1. **身份推断不使用当前日期**。学生/社招的判定只依赖简历自身信号
   （校园经历、教育时段是否"至今"、学位层次），不引入 datetime.now()——
   否则同一输入在不同时间会得出不同结论，直接违反 NFR-08。
2. **页数按文本量估算**。解析结果不含版式信息，用结构化文本总量 +
    未识别内容估算（约 800 字/页），估算依据写入 evidence 与 meta，
    判定过程对用户与测试透明，而非伪装成精确页数。
3. **位置检查利用 trace 的文档顺序**。structurer 按行序追加 trace，
    因此 trace 下标即"信息在文档中出现的位置"代理，无需重新读取原文件。
"""
import math
import time

from app.diagnosis.base import DiagnosisContext, DiagnosisModule
from app.diagnosis.models import (
    DIM_STRUCTURE,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    DiagnosisResult,
    Issue,
    Location,
    build_result,
)
from app.diagnosis import rules

RULE_VERSION = "structure-1.0.0"

# 页数估算：一页 A4 中文简历（常规字号与行距）约可容纳的字符数
CHARS_PER_PAGE = 800

# 篇幅占比判定仅在总篇幅达到该阈值后进行，避免短简历被噪声支配
MIN_TOTAL_CHARS = 400
# 经历（实习 + 项目）占总篇幅的下限：HR 最关心"做过什么"
MIN_CORE_RATIO = 0.25
# 荣誉奖项占总篇幅的上限：超过则挤压经历空间
MAX_HONOR_RATIO = 0.20

# 联系方式出现过深的位置阈值（占 trace 总量比例）：应出现在文档头部
CONTACT_DEPTH_RATIO = 0.6
# 姓名应出现的位置（trace 前 N 条）
NAME_TOP_N = 3

# 经历类区块（用于"开篇区块"与身份推断）
_CORE_SECTIONS = ("education", "experience", "projects")
_STUDENT_DEGREES = ("本科", "学士", "大专", "专科", "bachelor")


def _section_chars(structure: dict, unrecognized: list | None) -> dict[str, int]:
    """统计各区块字符量（篇幅占比与页数估算的输入）。"""
    counts: dict[str, int] = {}
    basic = structure.get("basic_info") or {}
    counts["basic_info"] = sum(len(str(v)) for v in basic.values() if v)

    for section in ("education", "experience", "projects", "skills", "honors"):
        total = 0
        for item in structure.get(section) or []:
            if isinstance(item, dict):
                total += sum(len(str(v)) for v in item.values() if v)
            elif item:
                total += len(str(item))
        counts[section] = total

    counts["unrecognized"] = sum(
        len(str((u or {}).get("text") or "")) for u in (unrecognized or [])
    )
    return counts


def _infer_identity(structure: dict) -> tuple[str, str]:
    """推断求职者身份（student / professional / unknown）与判定依据。

    只使用简历自身信号，不依赖当前日期（NFR-08 可复现）。
    """
    experience = structure.get("experience") or []
    education = structure.get("education") or []

    # 正式工作经历：单位名不含"校园"等学生场景词
    has_work = any(
        "校园" not in str((item or {}).get("company") or "")
        and "校园" not in str((item or {}).get("role") or "")
        and (item or {}).get("company")
        for item in experience
    )
    has_campus = any(
        "校园" in str((item or {}).get("company") or "")
        or "校园" in str((item or {}).get("role") or "")
        for item in experience
    )

    # 教育时段"至今/现在" → 在读
    studying = any(
        rules.period_months((item or {}).get("period"))[2] for item in education
    )
    junior_degree = any(
        any(d in str((item or {}).get("degree") or "") for d in _STUDENT_DEGREES)
        for item in education
    )

    if has_work:
        return "professional", "存在单位名非校园场景的实习/工作经历"
    if studying:
        return "student", "教育背景时间段为开放式（至今/现在），推断在读"
    if has_campus:
        return "student", "经历中命中校园场景（校园经历）"
    if junior_degree and not experience:
        return "student", "最高学历为本科/专科且无实习经历条目"
    return "unknown", "身份信号不足，跳过页数匹配判定"


def _trace_index(trace: list, field: str) -> int | None:
    """字段在 trace 中的首个下标（文档顺序代理）。"""
    for idx, item in enumerate(trace):
        if (item or {}).get("field") == field:
            return idx
    return None


def _first_section(trace: list) -> str | None:
    """文档中第一个章节区块（section.* 形式的 trace）。"""
    for item in trace:
        field = (item or {}).get("field") or ""
        if field.startswith("section."):
            return field.split(".", 1)[1]
    return None


class StructureModule(DiagnosisModule):
    """结构与篇幅体检（FR-07）。"""

    dimension = DIM_STRUCTURE
    module_name = "structure_layout"
    rule_version = RULE_VERSION

    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        start = time.perf_counter()
        structure = ctx.structure or {}
        trace = ctx.trace or []
        unrecognized = ctx.unrecognized or []
        issues: list[Issue] = []

        counts = _section_chars(structure, unrecognized)
        total_chars = sum(counts.values())
        identity, identity_basis = _infer_identity(structure)
        estimated_pages = max(1, math.ceil(total_chars / CHARS_PER_PAGE))

        issues.extend(self._check_module_completeness(structure))
        issues.extend(self._check_page_count(identity, identity_basis, estimated_pages, total_chars))
        issues.extend(self._check_proportion(counts, total_chars))
        issues.extend(self._check_key_info_position(structure, trace))

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return build_result(
            resume_id=ctx.resume_id,
            dimension=self.dimension,
            module_name=self.module_name,
            issues=issues,
            rule_version=self.rule_version,
            elapsed_ms=elapsed,
            reproducible=True,
            meta={
                "checks": 4,
                "estimated_pages": estimated_pages,
                "total_chars": total_chars,
                "identity": identity,
                "identity_basis": identity_basis,
                "section_chars": counts,
            },
        )

    # ---------- 模块完整性 ----------
    def _check_module_completeness(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        basic = structure.get("basic_info") or {}

        if not basic.get("name"):
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="模块缺失·姓名",
                    location=Location(field="basic_info.name", snippet=""),
                    problem="简历中未识别到姓名",
                    suggestion="请在文档开头清晰标注姓名（HR 与面试官的第一参照）",
                    evidence="结构化结果 basic_info.name 为空",
                )
            )

        if not (structure.get("education") or []):
            issues.append(
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="模块缺失·教育背景",
                    location=Location(field="education", snippet=""),
                    problem="简历缺少教育背景区块",
                    suggestion="请补充学校、专业、学历与在读时间；应届生应将教育背景置于简历前部",
                    evidence="结构化结果 education 为空数组",
                )
            )

        if not (structure.get("experience") or []) and not (structure.get("projects") or []):
            issues.append(
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="模块缺失·经历",
                    location=Location(field="experience", snippet=""),
                    problem="简历既无实习经历也无项目经历",
                    suggestion="请补充至少一段经历（实习/项目/竞赛均可），写清角色与产出",
                    evidence="结构化结果 experience 与 projects 均为空数组",
                )
            )
        return issues

    # ---------- 页数与身份匹配度 ----------
    def _check_page_count(
        self,
        identity: str,
        identity_basis: str,
        estimated_pages: int,
        total_chars: int,
    ) -> list[Issue]:
        if identity == "unknown":
            # 身份信号不足时不判定——误报比漏报更伤产品可信度
            return []
        limit = 1 if identity == "student" else 2
        if estimated_pages <= limit:
            return []
        label = "应届生/学生" if identity == "student" else "社招"
        return [
            Issue(
                severity=SEVERITY_MAJOR,
                category="页数与身份不匹配",
                location=Location(field="_document", snippet=""),
                problem=f"按{label}标准简历应控制在 {limit} 页，当前约 {estimated_pages} 页",
                suggestion=(
                    "删减与目标岗位无关的内容，合并表述重复的经历，"
                    "把空间留给最能证明能力的 2-3 段经历"
                ),
                evidence=(
                    f"结构化文本总量 {total_chars} 字，按每页约 {CHARS_PER_PAGE} 字估算约 "
                    f"{estimated_pages} 页；身份判定：{identity_basis}"
                ),
            )
        ]

    # ---------- 篇幅占比 ----------
    def _check_proportion(self, counts: dict[str, int], total_chars: int) -> list[Issue]:
        issues: list[Issue] = []
        if total_chars < MIN_TOTAL_CHARS:
            return issues

        core = counts.get("experience", 0) + counts.get("projects", 0)
        if core / total_chars < MIN_CORE_RATIO:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="经历篇幅占比过低",
                    location=Location(field="experience", snippet=""),
                    problem=(
                        f"实习/项目经历仅占总篇幅 {core / total_chars:.0%}，"
                        "简历重心不在经历上"
                    ),
                    suggestion=(
                        "压缩基本信息与荣誉的篇幅，把经历扩写成「动作 + 方法 + 结果」的完整表述"
                    ),
                    evidence=(
                        f"经历类字符 {core} / 总字符 {total_chars} < 阈值 "
                        f"{MIN_CORE_RATIO:.0%}"
                    ),
                )
            )

        honors = counts.get("honors", 0)
        if honors / total_chars > MAX_HONOR_RATIO:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="荣誉占比过高",
                    location=Location(field="honors", snippet=""),
                    problem=f"荣誉奖项占总篇幅 {honors / total_chars:.0%}，挤压了经历空间",
                    suggestion="只保留与目标岗位相关的 2-3 项荣誉，其余删除或合并",
                    evidence=(
                        f"荣誉字符 {honors} / 总字符 {total_chars} > 阈值 "
                        f"{MAX_HONOR_RATIO:.0%}"
                    ),
                )
            )
        return issues

    # ---------- 关键信息位置 ----------
    def _check_key_info_position(self, structure: dict, trace: list) -> list[Issue]:
        issues: list[Issue] = []
        if not trace:
            return issues

        total = len(trace)
        # 联系方式应出现在文档头部（占比前 CONTACT_DEPTH_RATIO 以内）
        contact_idx = None
        for field in ("basic_info.phone", "basic_info.email"):
            idx = _trace_index(trace, field)
            if idx is not None and (contact_idx is None or idx < contact_idx):
                contact_idx = idx
        if contact_idx is not None and total >= 5 and contact_idx > total * CONTACT_DEPTH_RATIO:
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="联系方式位置过深",
                    location=Location(field="basic_info.phone", snippet=""),
                    problem="联系方式出现在文档过于靠后的位置",
                    suggestion="把姓名与联系方式移到文档最顶部的基本信息区，确保第一屏可见",
                    evidence=(
                        f"联系方式在 {total} 条解析记录中位于第 {contact_idx + 1} 条，"
                        f"超过深度阈值 {CONTACT_DEPTH_RATIO:.0%}"
                    ),
                )
            )

        # 姓名应出现在文档最开头
        name_idx = _trace_index(trace, "basic_info.name")
        if name_idx is not None and name_idx >= NAME_TOP_N:
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="姓名位置不佳",
                    location=Location(field="basic_info.name", snippet=""),
                    problem="姓名没有出现在文档开头",
                    suggestion="将姓名置于首行或首行附近，方便快速识别简历归属",
                    evidence=f"姓名在解析记录中位于第 {name_idx + 1} 条，未进入前 {NAME_TOP_N} 条",
                )
            )

        # 开篇区块：技能/荣誉打头会把最关键的经历挤到后面
        first_section = _first_section(trace)
        if first_section in ("skills", "honors"):
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="开篇区块不当",
                    location=Location(field=f"section.{first_section}", snippet=""),
                    problem="简历以技能/荣誉区块开篇，教育背景与经历被挤到后面",
                    suggestion="调整区块顺序：教育背景 → 实习/项目经历 → 技能 → 荣誉",
                    evidence=f"文档第一个章节区块为 {first_section}",
                )
            )
        return issues


MODULE = StructureModule()
