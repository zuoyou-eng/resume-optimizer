"""FR-04 基础规范体检模块。

检查项（与需求文档表格逐条对应）：
  联系方式错误 / 无关个人信息 / 中英文标点混用 / 日期格式不一致
  时间线倒序 / 时间断层 / 错别字病句

全部为确定性规则 → reproducible=True，可直接按固定输入断言输出（NFR-08）。
"""
import re
import time

from app.diagnosis.base import DiagnosisContext, DiagnosisModule
from app.diagnosis.models import (
    DIM_NORM,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    DiagnosisResult,
    Issue,
    Location,
    build_result,
)
from app.diagnosis import rules

RULE_VERSION = "norm-1.0.0"

# 参与检查的文本字段：(结构键, 条目内字段)
# period 必须纳入——日期格式一致性检查漏掉它就等于漏掉最关键的字段
_TEXT_FIELDS = [
    ("education", ["school", "major", "degree", "period", "description"]),
    ("experience", ["company", "role", "period", "description"]),
    ("projects", ["name", "role", "period", "description"]),
]

# 日期书写格式归类（用于"日期格式不一致"检测）
_DATE_FORMATS = [
    (re.compile(r"\d{4}\.\d{1,2}"), "2021.09"),
    (re.compile(r"\d{4}/\d{1,2}"), "2021/09"),
    (re.compile(r"\d{4}-\d{1,2}"), "2021-09"),
    (re.compile(r"\d{4}年\d{1,2}月"), "2021年9月"),
]


def _iter_texts(structure: dict):
    """遍历结构化简历的全部文本字段，产出 (字段路径, 文本)。"""
    basic = structure.get("basic_info") or {}
    for key in ("name", "phone", "email", "city"):
        value = basic.get(key)
        if value:
            yield f"basic_info.{key}", value

    for section, fields in _TEXT_FIELDS:
        for idx, item in enumerate(structure.get(section) or []):
            for f in fields:
                value = (item or {}).get(f)
                if value:
                    yield f"{section}[{idx}].{f}", value

    for idx, skill in enumerate(structure.get("skills") or []):
        if skill:
            yield f"skills[{idx}]", skill
    for idx, honor in enumerate(structure.get("honors") or []):
        if honor:
            yield f"honors[{idx}]", honor


def _classify_date_formats(text: str) -> set[str]:
    found = set()
    for pattern, label in _DATE_FORMATS:
        if pattern.search(text):
            found.add(label)
    return found


class NormModule(DiagnosisModule):
    """基础规范体检（FR-04）。"""

    dimension = DIM_NORM
    module_name = "norm_check"
    rule_version = RULE_VERSION

    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        start = time.perf_counter()
        structure = ctx.structure or {}
        issues: list[Issue] = []

        issues.extend(self._check_contact(structure))
        issues.extend(self._check_irrelevant_info(structure))
        issues.extend(self._check_punctuation(structure))
        issues.extend(self._check_date_format_consistency(structure))
        issues.extend(self._check_timeline(structure, "education", "教育背景"))
        issues.extend(self._check_timeline(structure, "experience", "实习经历"))
        issues.extend(self._check_timeline(structure, "projects", "项目经历"))
        issues.extend(self._check_typos_and_prose(structure))

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return build_result(
            resume_id=ctx.resume_id,
            dimension=self.dimension,
            module_name=self.module_name,
            issues=issues,
            rule_version=self.rule_version,
            elapsed_ms=elapsed,
            reproducible=True,
            meta={"checks": 7},
        )

    # ---------- 联系方式 ----------
    def _check_contact(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        basic = structure.get("basic_info") or {}

        if not basic.get("phone"):
            issues.append(
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="联系方式缺失",
                    location=Location(field="basic_info.phone", snippet=""),
                    problem="简历中未识别到手机号码",
                    suggestion="请在基本信息区补充可接通的手机号码（HR 联系你的第一途径）",
                    evidence="结构化结果 basic_info.phone 为空",
                )
            )
        else:
            phone = str(basic["phone"])
            # 11 位数字但号段非法（如 10/12/16 开头）→ 疑似输错
            m = rules.SUSPECT_MOBILE_RE.search(phone)
            if m and not rules.VALID_MOBILE_RE.search(m.group(1)):
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="联系方式错误",
                        location=Location(field="basic_info.phone", snippet=phone),
                        problem=f"手机号 {phone} 不是有效的号段",
                        suggestion="请核对手机号是否输错一位",
                        evidence="号段首位为 1，但第二位不在 3-9 范围内",
                    )
                )

        if not basic.get("email"):
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="联系方式缺失",
                    location=Location(field="basic_info.email", snippet=""),
                    problem="简历中未识别到电子邮箱",
                    suggestion="建议补充常用邮箱，部分企业会通过邮件发送笔试/面试链接",
                    evidence="结构化结果 basic_info.email 为空",
                )
            )
        else:
            email = str(basic["email"])
            if not rules.EMAIL_VALID_RE.match(email):
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="联系方式错误",
                        location=Location(field="basic_info.email", snippet=email),
                        problem=f"邮箱地址 {email} 格式不完整",
                        suggestion="请检查邮箱是否缺少域名后缀（如 @qq.com）",
                        evidence="邮箱缺少顶级域名（形如 name@domain.com）",
                    )
                )
        return issues

    # ---------- 无关个人信息 ----------
    def _check_irrelevant_info(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        for field_path, text in _iter_texts(structure):
            for label, pattern in rules.IRRELEVANT_PERSONAL_INFO:
                m = pattern.search(text)
                if m:
                    issues.append(
                        Issue(
                            severity=SEVERITY_MINOR,
                            category="无关个人信息",
                            location=Location(field=field_path, snippet=text[:60]),
                            problem=f"简历中包含「{label}」，与岗位能力无关",
                            suggestion="建议删除该信息——既占篇幅，也可能引发无意识偏见",
                            evidence=f"命中无关信息规则：{label}",
                        )
                    )
                    break  # 同一字段只报一次
        return issues

    # ---------- 中英文标点混用 ----------
    def _check_punctuation(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        for field_path, text in _iter_texts(structure):
            if len(text) < 8:
                continue
            has_cn = any(p in text for p in rules.CN_PUNCT)
            has_en = any(p in text for p in rules.EN_PUNCT)
            if has_cn and has_en:
                issues.append(
                    Issue(
                        severity=SEVERITY_MINOR,
                        category="中英文标点混用",
                        location=Location(field=field_path, snippet=text[:60]),
                        problem="同一句里中英文标点混用",
                        suggestion="中文内容请统一使用中文标点，纯英文段落统一使用英文标点",
                        evidence="该文本同时包含中文标点与英文标点",
                    )
                )
        return issues

    # ---------- 日期格式一致性 ----------
    def _check_date_format_consistency(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        found: dict[str, str] = {}
        for field_path, text in _iter_texts(structure):
            for fmt in _classify_date_formats(text):
                found.setdefault(fmt, field_path)

        if len(found) > 1:
            samples = "、".join(f"{fmt}（见 {found[fmt]}）" for fmt in sorted(found))
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="日期格式不一致",
                    location=Location(field=list(found.values())[0], snippet=""),
                    problem=f"简历中出现了 {len(found)} 种日期写法",
                    suggestion="请统一为一种写法（推荐 2021.09），避免 HR 扫读时反复适应格式",
                    evidence=f"检测到多种格式并存：{samples}",
                )
            )
        return issues

    # ---------- 时间线：倒序 + 断层 ----------
    def _check_timeline(self, structure: dict, section: str, label: str) -> list[Issue]:
        issues: list[Issue] = []
        items = structure.get(section) or []
        parsed: list[tuple[int, tuple, tuple | None, bool, str]] = []

        for idx, item in enumerate(items):
            period = (item or {}).get("period")
            start, end, ongoing = rules.period_months(period)
            if start:
                parsed.append((idx, start, end, ongoing, period or ""))

        # 倒序：最近的经历应排在前面；后一条起始更晚 → 顺序颠倒
        for (i, s1, _, _, p1), (j, s2, _, _, p2) in zip(parsed, parsed[1:]):
            if rules.month_diff(s1, s2) > 0:
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="时间线倒序",
                        location=Location(
                            field=f"{section}[{j}].period", snippet=f"{p1} / {p2}"
                        ),
                        problem=f"{label}未按时间倒序排列（第 {j + 1} 条比第 {i + 1} 条更近）",
                        suggestion="请把最新的经历放在最前面——HR 通常只认真读前两条",
                        evidence=f"第 {i + 1} 条起始 {p1}，第 {j + 1} 条起始 {p2}",
                    )
                )

        # 断层：相邻经历之间空白超过阈值（开放式"至今"不参与计算）
        for (i, _, end1, ongoing1, p1), (j, start2, _, _, p2) in zip(parsed, parsed[1:]):
            if end1 is None or ongoing1:
                continue
            gap = rules.month_diff(end1, start2)
            if gap > rules.GAP_MONTHS:
                issues.append(
                    Issue(
                        severity=SEVERITY_MINOR,
                        category="时间断层",
                        location=Location(
                            field=f"{section}[{j}].period", snippet=f"{p1} → {p2}"
                        ),
                        problem=f"{label}中存在约 {gap} 个月的空窗期",
                        suggestion="如有短期实习/项目/课程可补上；若确实空白，可准备一句合理说明应对面试提问",
                        evidence=f"第 {i + 1} 条结束于 {p1}，第 {j + 1} 条开始于 {p2}",
                    )
                )
        return issues

    # ---------- 错别字 / 病句 ----------
    def _check_typos_and_prose(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        for field_path, text in _iter_texts(structure):
            for wrong, right in rules.COMMON_TYPOS.items():
                if wrong in text:
                    issues.append(
                        Issue(
                            severity=SEVERITY_MINOR,
                            category="错别字",
                            location=Location(field=field_path, snippet=text[:60]),
                            problem=f"检测到重复用字「{wrong}」",
                            suggestion=f"请改为「{right}」",
                            evidence="连续重复单字，多为输入法误触",
                        )
                    )
                    break
            else:
                for wrong, right in rules.TYPO_WORDS:
                    if wrong in text:
                        issues.append(
                            Issue(
                                severity=SEVERITY_MINOR,
                                category="错别字",
                                location=Location(field=field_path, snippet=text[:60]),
                                problem=f"检测到疑似错别字「{wrong}」",
                                suggestion=f"请确认是否应为「{right}」",
                                evidence=f"命中易错词表：{wrong} → {right}",
                            )
                        )
                        break

        # 病句式表达：经历/项目描述过短，信息量不足
        for section in ("experience", "projects"):
            for idx, item in enumerate(structure.get(section) or []):
                desc = ((item or {}).get("description") or "").strip()
                if desc and len(desc) < rules.MIN_DESC_LENGTH:
                    issues.append(
                        Issue(
                            severity=SEVERITY_MINOR,
                            category="描述过于简略",
                            location=Location(field=f"{section}[{idx}].description", snippet=desc),
                            problem=f"{section}[{idx}] 的描述仅 {len(desc)} 字，信息量不足",
                            suggestion="建议补充：做了什么 / 用了什么方法 / 结果如何",
                            evidence=f"描述长度 {len(desc)} < 阈值 {rules.MIN_DESC_LENGTH}",
                        )
                    )
        return issues


MODULE = NormModule()
