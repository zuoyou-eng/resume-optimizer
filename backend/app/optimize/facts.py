"""事实抽取器（设计文档 4.5.7 可测试性措施 #1）。

把"改写是否编造"这个主观判断变成**集合比对**：
抽取改写前的事实清单 A 与改写后的事实清单 B，逐项比对得到
preserved（守恒）/ violated（被改变）/ added（新增）。

`violated` 或 `added` 非空 → 判定该改写失败，不返回给用户。
关键取舍：**宁可改写失败，也不返回可能编造的内容。**
"""
import re
from dataclasses import dataclass, field

from app.diagnosis.rules import parse_year_month
# 正则统一从解析层取，避免同一规则在两处漂移
from app.parser.structurer import (
    COMPANY_EN_RE,
    COMPANY_RE,
    DEGREE_RE,
    PERIOD_RE,
    ROLE_EN_RE,
    ROLE_RE,
    SCHOOL_RE,
)

# 事实类别（设计文档 4.5.1：学校 / 单位 / 时间 / 数字 / 职称 / 技术名词）
KIND_SCHOOL = "school"
KIND_COMPANY = "company"
KIND_TIME = "time"
KIND_NUMBER = "number"
KIND_TITLE = "title"
KIND_TECH = "tech"
KIND_DEGREE = "degree"
KIND_CLAIM = "claim"  # 评价性主张（好评/优秀/显著等）

# 技术名词表（用于事实抽取与"怎么做"要素判定）
TECH_TERMS = [
    "Python", "Java", "Go", "Golang", "C++", "JavaScript", "TypeScript",
    "Vue", "React", "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB",
    "Docker", "Kubernetes", "K8s", "Linux", "Git", "FastAPI", "Django",
    "Flask", "Spring", "SpringBoot", "Pandas", "Spark", "Flink", "Kafka",
    "CI/CD", "NLP", "爬虫", "微服务", "自动化测试", "接口测试", "性能测试",
]

# 评价性主张：这类表述是"原文没有就不能加"的典型——系统擅自补一句
# "获得一致好评"与编造一个数字同样严重，因此也纳入事实清单参与守恒比对。
CLAIM_TERMS = [
    "一致好评", "好评", "认可", "表扬", "嘉奖", "赞誉", "优秀", "突出",
    "显著", "大幅", "圆满", "一致认可", "高度评价", "广受",
]

_NUMBER_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|万|千|百|亿|人|次|天|小时|个|条|倍|ms|s|QPS|TPS|GB|MB)"
    r"|(?<!\d)\d{3,}(?!\d)"
)
# GPA 一类的小数也作为事实（避免"GPA 3.6"被当作可删除内容）
_GPA_RE = re.compile(r"GPA\s*\d+(?:\.\d+)?", re.IGNORECASE)

# 学校名核心：SCHOOL_RE 的字符类较宽，可能把"月 在"这类前缀吃进来
# （如"2024年6月 在浙江大学"会匹配到"月 在浙江大学"）。此处只取尾部核心，
# 使"不同写法的同一所学校"能被判定为同一事实。
_SCHOOL_CORE_RE = re.compile(r"[一-龥A-Za-z]{2,12}(?:大学|学院|学校|University|College)\s*$")

# 学校名前容易被误吞的虚词（"2024年6月 在浙江大学" → "在浙江大学"）
_PREFIX_STRIP = "在于是月有和与及从到被把将向对为的就都也还又并而且"


def _clean_school(value: str) -> str:
    m = _SCHOOL_CORE_RE.search(value)
    core = m.group(0).strip() if m else value.strip()
    # 去掉误吞的虚词前缀："在浙江大学" → "浙江大学"（"国防科技大学"这类不受影响）
    while core and core[0] in _PREFIX_STRIP:
        core = core[1:]
    return core


@dataclass(frozen=True)
class Fact:
    """单条事实：类别 + 标准化值（比对用）+ 原文（展示用）。"""

    kind: str
    value: str
    raw: str

    def key(self) -> tuple[str, str]:
        return (self.kind, self.value)


@dataclass
class FactSet:
    facts: list[Fact] = field(default_factory=list)

    def keys(self) -> set[tuple[str, str]]:
        return {f.key() for f in self.facts}

    def to_list(self) -> list[dict]:
        return [{"kind": f.kind, "value": f.value, "raw": f.raw} for f in self.facts]

    def __len__(self) -> int:
        return len(self.facts)


def _dedup(facts: list[Fact]) -> list[Fact]:
    seen: set[tuple[str, str]] = set()
    out: list[Fact] = []
    for f in facts:
        if f.key() in seen:
            continue
        seen.add(f.key())
        out.append(f)
    return out


def extract_facts(text: str) -> FactSet:
    """从一段文本中抽取结构化事实（确定性规则 → 可复现、可单测）。"""
    if not text:
        return FactSet()
    facts: list[Fact] = []

    # 学校
    for m in SCHOOL_RE.finditer(text):
        facts.append(Fact(KIND_SCHOOL, _clean_school(m.group(0)), m.group(0)))

    # 单位（中文 + 英文）
    for pattern in (COMPANY_RE, COMPANY_EN_RE):
        for m in pattern.finditer(text):
            value = m.group(0).strip()
            if value:
                facts.append(Fact(KIND_COMPANY, value, m.group(0)))

    # 时间（归一化为 YYYYMM，使 2021.09 与 2021年9月 视为同一事实）
    for m in PERIOD_RE.finditer(text):
        for token in re.split(r"[-–—~至]", m.group(0)):
            ym = parse_year_month(token)
            if ym:
                facts.append(Fact(KIND_TIME, f"{ym[0]:04d}{ym[1]:02d}", token.strip()))

    # 学位
    for m in DEGREE_RE.finditer(text):
        facts.append(Fact(KIND_DEGREE, m.group(0).lower(), m.group(0)))

    # 职称 / 职位
    for m in ROLE_RE.finditer(text):
        value = m.group(0).strip()
        if value:
            facts.append(Fact(KIND_TITLE, value, m.group(0)))
    for m in ROLE_EN_RE.finditer(text):
        value = m.group(0).strip()
        if value:
            facts.append(Fact(KIND_TITLE, value, m.group(0)))

    # 技术名词
    for term in TECH_TERMS:
        if re.search(rf"(?<![A-Za-z0-9+/#.\-]){re.escape(term)}(?![A-Za-z0-9+/#.\-])", text, re.IGNORECASE):
            facts.append(Fact(KIND_TECH, term.lower(), term))

    # 评价性主张（同样参与守恒比对）
    for term in CLAIM_TERMS:
        if term in text:
            facts.append(Fact(KIND_CLAIM, term, term))

    # 数字（含单位）与 GPA
    # 先屏蔽时间段区间：否则"2023.06-2023.12"里的 2023 会被当成独立数字事实，
    # 改写日期时误报 violated——时间已经是 KIND_TIME 事实，不应重复计数。
    masked = text
    for m in PERIOD_RE.finditer(text):
        masked = masked.replace(m.group(0), "　" * len(m.group(0)))
    for m in _NUMBER_UNIT_RE.finditer(masked):
        facts.append(Fact(KIND_NUMBER, re.sub(r"\s+", "", m.group(0)), m.group(0)))
    for m in _GPA_RE.finditer(text):
        facts.append(Fact(KIND_NUMBER, re.sub(r"\s+", "", m.group(0)).lower(), m.group(0)))

    return FactSet(_dedup(facts))


@dataclass
class FactCheckReport:
    """事实比对报告（设计文档 4.5.2）。"""

    facts_before: list[dict] = field(default_factory=list)
    facts_after: list[dict] = field(default_factory=list)
    preserved: list[dict] = field(default_factory=list)
    violated: list[dict] = field(default_factory=list)
    added: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """守恒判定：既不允许事实被改变，也不允许新增原文没有的事实。"""
        return not self.violated and not self.added

    def to_dict(self) -> dict:
        return {
            "facts_before": self.facts_before,
            "facts_after": self.facts_after,
            "preserved": self.preserved,
            "violated": self.violated,
            "added": self.added,
            "passed": self.passed,
        }


def compare_facts(before_text: str, after_text: str) -> FactCheckReport:
    """前后事实比对： violated / added 非空即判定失败。"""
    a = extract_facts(before_text)
    b = extract_facts(after_text)

    preserved = sorted(a.keys() & b.keys())
    violated = sorted(a.keys() - b.keys())
    added = sorted(b.keys() - a.keys())

    a_by_key = {f.key(): f for f in a.facts}
    b_by_key = {f.key(): f for f in b.facts}

    return FactCheckReport(
        facts_before=a.to_list(),
        facts_after=b.to_list(),
        preserved=[_fact_dict(a_by_key[k]) for k in preserved],
        violated=[_fact_dict(a_by_key[k]) for k in violated],
        added=[_fact_dict(b_by_key[k]) for k in added],
    )


def _fact_dict(f: Fact) -> dict:
    return {"kind": f.kind, "value": f.value, "raw": f.raw}
