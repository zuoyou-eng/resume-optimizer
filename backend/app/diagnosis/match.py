"""FR-08 岗位匹配度分析模块（设计文档 4.4）。

处理链路：岗位描述 → 关键要求提取 → 与简历逐项比对 → 三档结论 → 匹配评分

三档结论（设计文档原文）：
  已覆盖 covered     简历中有明确对应的经历或技能 → 给出对应证据位置
  部分覆盖 partial    有相关经历但呈现不足 → 提示可强化的点
  完全缺失 missing    简历中未体现该要求 → 标注"需长期积累"或"可短期补充"

与 ATS 模块的关系（设计文档 4.4）：两者都是"简历 × 另一份文本"的比对，
共用同一套比对框架，只是比对对象不同（机器读取规则 / 岗位要求）。
因此本模块的 compare() 与 machine 模块的 _is_prefix_truncated 同属比对组件。
"""
import re
import time
from datetime import datetime

from app.diagnosis.base import DiagnosisContext, DiagnosisModule
from app.diagnosis.models import (
    DIM_MATCH,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    DiagnosisResult,
    Issue,
    Location,
    build_result,
)
from app.diagnosis import rules

RULE_VERSION = "match-1.0.0"

# 三档结论
COVERED = "covered"
PARTIAL = "partial"
MISSING = "missing"

VERDICT_LABELS = {COVERED: "已覆盖", PARTIAL: "部分覆盖", MISSING: "完全缺失"}

# 相关技能组：组内任意命中即视为"部分覆盖"（同域工具链）
SKILL_GROUPS = [
    {"Docker", "Kubernetes", "K8s", "容器"},
    {"MySQL", "PostgreSQL", "SQL", "数据库"},
    {"Redis", "MongoDB", "缓存"},
    {"Django", "Flask", "FastAPI", "后端框架"},
    {"Vue", "React", "前端框架"},
    {"Pandas", "数据分析"},
    {"Kafka", "Flink", "Spark", "大数据"},
    {"接口测试", "自动化测试", "测试", "性能测试"},
]

# 需要长期积累的能力（语言 / 框架 / 算法 / 领域知识）
LONG_TERM = {
    "python", "java", "go", "golang", "c++", "javascript", "typescript",
    "react", "vue", "django", "spring", "机器学习", "深度学习", "nlp",
    "数据分析", "微服务", "算法",
}
# 可短期补齐的能力（工具 / 流程 / 文档）
SHORT_TERM_HINT = "可短期补充"
LONG_TERM_HINT = "需长期积累"

# 经验年限要求："3 年以上经验" / "至少 2 年" / "3 年以上后端开发经验"
YEARS_RE = re.compile(r"(\d+)\s*年(?:以上|及以上)?[^\d，。；、\n]{0,8}?经验")
# 学历要求："本科及以上学历" / "硕士学历"
DEGREE_REQ_RE = re.compile(r"(大专|专科|本科|学士|硕士|研究生|博士|PhD|Master|Bachelor)", re.IGNORECASE)


def contains_term(haystack_lower: str, term_lower: str) -> bool:
    """判断文本中是否包含某个技能词。

    纯 ASCII 技能名要求**词边界**，否则会出现子串误配：
    "Django" 会命中 "Go"、"MySQL" 会命中 "SQL"——这类误配直接导致
    匹配评分虚高/虚低，且难以察觉，因此在此统一收口。
    """
    if term_lower.isascii():
        pattern = (
            rf"(?<![a-z0-9+/#.\-]){re.escape(term_lower)}(?![a-z0-9+/#.\-])"
        )
        return re.search(pattern, haystack_lower) is not None
    return term_lower in haystack_lower


# ---------- 关键要求提取（服务端在保存 JD 时调用，结果存入 JobDescription.extracted_keys） ----------

def extract_jd_keys(raw_text: str) -> dict:
    """从岗位描述中提取关键要求（确定性规则 → 可复现、可单测）。"""
    text = raw_text or ""
    lower = text.lower()

    skills: list[str] = []
    for kw in rules.JD_SKILL_KEYWORDS:
        if contains_term(lower, kw.lower()):
            skills.append(kw)

    soft: list[str] = []
    squashed = lower.replace(" ", "")
    for kw in rules.JD_SOFT_KEYWORDS:
        if contains_term(squashed, kw.lower().replace(" ", "")):
            soft.append(kw)

    degree_req = ""
    degree_level = 0
    m = DEGREE_REQ_RE.search(text)
    if m:
        degree_req = m.group(1)
        degree_level = rules.DEGREE_LEVELS.get(degree_req, 0) or rules.DEGREE_LEVELS.get(
            degree_req.capitalize(), 0
        )

    years_req = 0
    ym = YEARS_RE.search(text)
    if ym:
        years_req = int(ym.group(1))

    return {
        "skills": skills,
        "soft": soft,
        "degree_req": degree_req,
        "degree_level": degree_level,
        "years_req": years_req,
    }


# ---------- 比对组件（与 ATS 模块共用的比对框架） ----------

def _resume_corpus(structure: dict) -> tuple[str, dict[str, str]]:
    """把结构化简历压成一份可检索文本，同时记录每个字段的原文（用于给出证据位置）。"""
    parts: list[str] = []
    origins: dict[str, str] = {}

    def add(field_path: str, value: str | None) -> None:
        if value:
            parts.append(value)
            origins.setdefault(value[:40], field_path)

    basic = structure.get("basic_info") or {}
    for key in ("name", "phone", "email", "city"):
        add(f"basic_info.{key}", basic.get(key))

    for section in ("education", "experience", "projects"):
        for idx, item in enumerate(structure.get(section) or []):
            for key, value in (item or {}).items():
                if isinstance(value, str):
                    add(f"{section}[{idx}].{key}", value)

    for idx, skill in enumerate(structure.get("skills") or []):
        add(f"skills[{idx}]", skill)
    for idx, honor in enumerate(structure.get("honors") or []):
        add(f"honors[{idx}]", honor)

    return "\n".join(parts), origins


def _find_evidence(needle: str, origins: dict[str, str]) -> str:
    """给出该要求在简历中的证据位置（设计文档 4.4：已覆盖需输出对应证据位置）。"""
    for value, field_path in origins.items():
        if needle.lower() in value.lower():
            return field_path
    return ""


def _resume_degree_level(structure: dict) -> tuple[int, str]:
    """取简历中最高学历等级。"""
    best, label = 0, ""
    for item in structure.get("education") or []:
        degree = (item or {}).get("degree") or ""
        for name, level in rules.DEGREE_LEVELS.items():
            if name.lower() in degree.lower() and level > best:
                best, label = level, degree
    return best, label


def _current_year_month() -> tuple[int, int]:
    today = datetime.now()
    return today.year, today.month


def _resume_total_months(
    structure: dict, now: tuple[int, int] | None = None
) -> int:
    """累加实习/项目经历的总月数，用于与 JD 年限要求比对。

    "至今"等开放式时间段按当前月份收尾；`now` 可注入以便测试固定结论
    （NFR-08：年限比对是唯一引入当前时间的地方，测试可注入固定值断言）。
    """
    total = 0
    for section in ("experience", "projects"):
        for item in structure.get(section) or []:
            start, end, ongoing = rules.period_months((item or {}).get("period"))
            if not start:
                continue
            if end is None:
                if not ongoing:
                    continue
                end = now or _current_year_month()
            span = rules.month_diff(start, end)
            if span > 0:
                total += span
    return total


class MatchModule(DiagnosisModule):
    """岗位匹配度分析（FR-08）。"""

    dimension = DIM_MATCH
    module_name = "job_match"
    rule_version = RULE_VERSION

    def __init__(self, now: tuple[int, int] | None = None):
        # now 可注入固定"当前月份"，使年限比对结论在测试中可复现
        self._now = now

    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        start = time.perf_counter()
        structure = ctx.structure or {}
        jd = ctx.jd or {}

        keys = jd.get("extracted_keys") or extract_jd_keys(jd.get("raw_text") or "")
        corpus, origins = _resume_corpus(structure)

        matches: list[dict] = []
        issues: list[Issue] = []

        # 1. 硬技能逐项比对
        matches.extend(self._match_skills(keys.get("skills") or [], corpus, origins, issues))

        # 2. 学历比对
        self._match_degree(keys, structure, matches, issues)

        # 3. 经验年限比对
        self._match_years(keys, structure, matches, issues)

        # 4. 软素质（仅作为提示，不参与缺口主清单）
        matches.extend(self._match_soft(keys.get("soft") or [], corpus, origins, issues))

        score = self._score(matches)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        gaps = [m for m in matches if m["verdict"] == MISSING]
        return build_result(
            resume_id=ctx.resume_id,
            dimension=self.dimension,
            module_name=self.module_name,
            issues=issues,
            rule_version=self.rule_version,
            elapsed_ms=elapsed,
            reproducible=True,
            # 匹配分来自"要求覆盖率"（4.4 节链路末步），不是问题扣分，必须显式传入
            score=score,
            meta={
                "jd_id": jd.get("id"),
                "jd_title": jd.get("title", ""),
                "requirement_count": len(matches),
                "matches": matches,
                "gaps": [g["requirement"] for g in gaps],
                "score_formula": "Σ权重(已覆盖=1, 部分覆盖=0.5) / Σ权重 × 100",
            },
        )

    # ---------- 硬技能 ----------
    def _match_skills(
        self,
        skills: list[str],
        corpus: str,
        origins: dict[str, str],
        issues: list[Issue],
    ) -> list[dict]:
        matches: list[dict] = []
        lower_corpus = corpus.lower()

        for skill in skills:
            needle = skill.lower()
            if contains_term(lower_corpus, needle):
                matches.append(
                    {
                        "requirement": skill,
                        "kind": "skill",
                        "verdict": COVERED,
                        "evidence": _find_evidence(skill, origins) or "简历正文",
                    }
                )
                continue

            # 同域工具链命中 → 部分覆盖
            related = self._related_hit(skill, lower_corpus)
            if related:
                matches.append(
                    {
                        "requirement": skill,
                        "kind": "skill",
                        "verdict": PARTIAL,
                        "evidence": f"简历中有相关技能「{related}」，但未直接体现 {skill}",
                    }
                )
                issues.append(
                    Issue(
                        severity=SEVERITY_MINOR,
                        category="岗位匹配·部分覆盖",
                        location=Location(field="skills", snippet=related),
                        problem=f"岗位要求「{skill}」，简历只体现了相关技能「{related}」",
                        suggestion=f"如实际用过 {skill}，请写明用了什么场景；若只用过 {related}，可准备面试说明",
                        evidence=f"同域技能组命中：{related}",
                    )
                )
            else:
                hint = LONG_TERM_HINT if needle in LONG_TERM else SHORT_TERM_HINT
                matches.append(
                    {
                        "requirement": skill,
                        "kind": "skill",
                        "verdict": MISSING,
                        "hint": hint,
                        "evidence": "简历全文未出现该技能",
                    }
                )
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="岗位匹配·技能缺失",
                        location=Location(field="skills", snippet=""),
                        problem=f"岗位要求「{skill}」，简历中完全没有体现",
                        suggestion=(
                            f"该技能{hint}：如有相关课程/项目经历请补充；"
                            "若确实不具备，建议优先投递匹配度更高的岗位"
                            if hint == LONG_TERM_HINT
                            else f"该技能{hint}：可快速补齐后在简历中补充"
                        ),
                        evidence="简历全文未匹配到该技能关键词",
                    )
                )
        return matches

    def _related_hit(self, skill: str, lower_corpus: str) -> str | None:
        target = skill.lower()
        for group in SKILL_GROUPS:
            names = {g.lower() for g in group}
            if target in names:
                for other in names:
                    if other != target and contains_term(lower_corpus, other):
                        return other
        return None

    # ---------- 学历 ----------
    def _match_degree(
        self, keys: dict, structure: dict, matches: list[dict], issues: list[Issue]
    ) -> None:
        req_level = keys.get("degree_level") or 0
        if not req_level:
            return
        mine, label = _resume_degree_level(structure)
        req_label = keys.get("degree_req") or ""
        if mine >= req_level:
            matches.append(
                {
                    "requirement": f"学历 {req_label}",
                    "kind": "degree",
                    "verdict": COVERED,
                    "evidence": label or "education[0].degree",
                }
            )
        else:
            matches.append(
                {
                    "requirement": f"学历 {req_label}",
                    "kind": "degree",
                    "verdict": MISSING,
                    "hint": LONG_TERM_HINT,
                    "evidence": label or "未识别到学历",
                }
            )
            issues.append(
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="岗位匹配·学历不符",
                    location=Location(field="education[0].degree", snippet=label),
                    problem=f"岗位要求「{req_label}」，简历学历为「{label or '未识别'}」",
                    suggestion="学历为硬性门槛，建议核对岗位要求后再投递",
                    evidence="简历最高学历等级低于岗位要求等级",
                )
            )

    # ---------- 经验年限 ----------
    def _match_years(
        self, keys: dict, structure: dict, matches: list[dict], issues: list[Issue]
    ) -> None:
        years_req = keys.get("years_req") or 0
        if not years_req:
            return
        months = _resume_total_months(structure, self._now)
        mine_years = round(months / 12, 1)
        if months >= years_req * 12:
            matches.append(
                {
                    "requirement": f"{years_req} 年以上经验",
                    "kind": "years",
                    "verdict": COVERED,
                    "evidence": f"实习/项目累计约 {mine_years} 年",
                }
            )
        elif months >= years_req * 12 * 0.6:
            matches.append(
                {
                    "requirement": f"{years_req} 年以上经验",
                    "kind": "years",
                    "verdict": PARTIAL,
                    "evidence": f"实习/项目累计约 {mine_years} 年，接近要求",
                }
            )
            issues.append(
                Issue(
                    severity=SEVERITY_MINOR,
                    category="岗位匹配·经验接近",
                    location=Location(field="experience", snippet=""),
                    problem=f"岗位要求 {years_req} 年以上经验，简历累计约 {mine_years} 年",
                    suggestion="可把最相关的经历前置并量化，突出与岗位同质的经验",
                    evidence=f"累计 {months} 个月，约为要求的 {round(months / (years_req * 12) * 100)}%",
                )
            )
        else:
            matches.append(
                {
                    "requirement": f"{years_req} 年以上经验",
                    "kind": "years",
                    "verdict": MISSING,
                    "hint": LONG_TERM_HINT,
                    "evidence": f"实习/项目累计约 {mine_years} 年",
                }
            )
            issues.append(
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="岗位匹配·经验不足",
                    location=Location(field="experience", snippet=""),
                    problem=f"岗位要求 {years_req} 年以上经验，简历累计约 {mine_years} 年",
                    suggestion="校招/实习岗位可重点突出项目深度与产出；如为社招要求，建议评估匹配度",
                    evidence=f"累计 {months} 个月 < 要求 {years_req * 12} 个月",
                )
            )

    # ---------- 软素质 ----------
    def _match_soft(
        self, soft: list[str], corpus: str, origins: dict[str, str], issues: list[Issue]
    ) -> list[dict]:
        matches: list[dict] = []
        squashed = corpus.lower().replace(" ", "")
        for kw in soft:
            if contains_term(squashed, kw.lower().replace(" ", "")):
                matches.append(
                    {
                        "requirement": kw,
                        "kind": "soft",
                        "verdict": COVERED,
                        "evidence": _find_evidence(kw, origins) or "简历正文",
                    }
                )
            else:
                matches.append(
                    {
                        "requirement": kw,
                        "kind": "soft",
                        "verdict": MISSING,
                        "hint": SHORT_TERM_HINT,
                        "evidence": "简历未体现",
                    }
                )
        return matches

    # ---------- 评分 ----------
    def _score(self, matches: list[dict]) -> int:
        """硬性要求（技能/学历/年限）计入评分，软素质仅作参考不计权。"""
        weights = {"skill": 1.0, "degree": 2.0, "years": 1.5}
        total = earned = 0.0
        for m in matches:
            w = weights.get(m["kind"])
            if w is None:
                continue
            total += w
            if m["verdict"] == COVERED:
                earned += w
            elif m["verdict"] == PARTIAL:
                earned += w * 0.5
        if total == 0:
            return 100
        return round(earned / total * 100)


MODULE = MatchModule()
