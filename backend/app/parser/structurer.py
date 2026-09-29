"""规则版结构化引擎：把提取出的文本行映射为结构化简历（FR-02）。

设计要点（对应《系统设计文档》）：
- 解析轨迹 trace：记录每个字段"从哪里、用什么规则读到"（4.3），让判定过程可追溯；
- 未识别内容显式收集（FR-03）：任何无法归入已知字段的原文都必须出现在
  unrecognized 中，严禁静默丢失；
- 规则集中在本文件、规则版本随结果落库（NFR-08 可复现）：相同输入 → 相同输出。

本实现为规则版（确定性、可单测），AI 结构化能力后续以同一接口接入。
"""
import re
from dataclasses import dataclass, field

# ---------- 章节识别（长词优先，避免"教育"抢先匹配"教育背景"；中英双语） ----------
SECTION_KEYWORDS: dict[str, list[str]] = {
    "education": ["教育背景", "教育经历", "学习经历", "教育", "Education"],
    "experience": ["工作经历", "实习经历", "工作经验", "实习经验", "社会实践", "校园经历", "社团经历", "学生工作", "工作与实习", "Work Experience", "Experience", "Internship"],
    "projects": ["项目经历", "项目经验", "项目", "Projects"],
    "skills": ["专业技能", "技术栈", "个人技能", "技能", "Skills"],
    "honors": ["荣誉奖项", "获奖情况", "获奖经历", "奖项", "荣誉", "证书", "获奖", "Honors", "Awards"],
    # 未归类区块：内容原样进入未识别池，不进任何结构字段（FR-03）。
    # 关键词刻意不用裸"其他"——"其他项目"这类标题必须仍然归到 projects。
    "other": ["未归类内容", "其他信息", "补充信息", "附件信息", "未分类内容"],
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
PHONE_LANDLINE_RE = re.compile(r"(?<!\d)(0\d{2,3}-?\d{7,8})(?!\d)")
# 城市后不能紧跟"大学/学院"（"南京大学"是校名不是城市），负向断言防误伤
CITY_RE = re.compile(
    r"(北京|上海|广州|深圳|杭州|成都|南京|武汉|西安|苏州|天津|重庆|长沙|郑州|青岛|厦门|合肥|福州|济南|大连|宁波|无锡)市?(?![大学院校])"
)
NAME_LABEL_RE = re.compile(r"^姓\s*名\s*[:：]?\s*([一-龥]{2,4})$")
PERIOD_RE = re.compile(
    r"(20\d{2}\s*[年./\-]?\s*(?:\d{1,2}\s*月?)?\s*[-–—~至]\s*"
    r"(?:20\d{2}\s*[年./\-]?\s*(?:\d{1,2}\s*月?)?|至今|现在|now|present))",
    re.IGNORECASE,
)
SCHOOL_RE = re.compile(r"[一-龥A-Za-z ]{2,20}?(?:大学|学院|学校|University|College)")
DEGREE_RE = re.compile(r"本科|硕士|博士|学士|研究生|大专|专科|MBA|博士后|Bachelor|Master|PhD", re.IGNORECASE)
COMPANY_RE = re.compile(
    r"[一-龥A-Za-z0-9]{2,30}(?:公司|科技|集团|有限|股份|事业部|中心|银行|传媒|网络|信息|研究院|实验室|工作室)"
)
ROLE_RE = re.compile(
    r"(?:后端|前端|测试|开发|算法|数据|产品|运营|设计|运维|研发|实习|项目|软件|系统|全栈)"
    r"[一-龥A-Za-z]*(?:工程师|开发|实习生|专员|经理|主管|设计师|分析师|岗|人员|师)"
)
COMPANY_EN_RE = re.compile(
    r"[A-Z][A-Za-z&.]*(?: [A-Z][A-Za-z&.]*)*(?: Inc| Ltd| LLC| Corp| Technologies| Tech| Labs| Group)\b"
)
ROLE_EN_RE = re.compile(
    r"(?:Backend|Frontend|Software|Data|Product|Test|DevOps|Full[- ]?Stack)[A-Za-z ]*"
    r"(?:Engineer|Developer|Intern|Manager|Designer|Analyst)"
)
# 前缀动词可叠加（如"熟练掌握"），用 + 量词一次剥净
SKILL_PREFIX_RE = re.compile(r"^(?:熟练|精通|熟悉|掌握|了解|会使用|具备|能够)+")
ITEM_LEAD_RE = re.compile(r"^[（(]?\d+[）).、\s]+")


@dataclass
class StructureResult:
    structure: dict = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    unrecognized: list[dict] = field(default_factory=list)


def _normalize_title(line: str) -> str:
    return re.sub(r"[\s【】\[\]#*=\-—~_|丨:：,，.。]", "", line)


def _detect_section(line: str) -> str | None:
    """判定一行是否为章节标题。标题必须短（<=15 字符）且与关键词高度吻合（大小写不敏感）。"""
    norm = _normalize_title(line)
    if not norm or len(norm) > 15:
        return None
    norm_lower = norm.lower()
    for section, keywords in SECTION_KEYWORDS.items():
        for kw in keywords:
            if norm == kw or norm.startswith(kw) or norm.endswith(kw) or norm_lower == kw.lower():
                return section
    return None


def _clean_snippet(line: str, limit: int = 60) -> str:
    return line[:limit] + ("…" if len(line) > limit else "")


def _split_entry_header(line: str) -> tuple[str | None, str]:
    """从条目头部行提取时间段，返回 (period, 剩余文本)。"""
    m = PERIOD_RE.search(line)
    if not m:
        return None, line.strip(" -–—~至|,，、")
    period = m.group(0).strip()
    rest = (line[: m.start()] + " " + line[m.end():]).strip(" -–—~至|,，、")
    return period, rest


def _parse_education_entry(header: str, desc_lines: list[str]) -> dict:
    period, rest = _split_entry_header(header)
    school_m = SCHOOL_RE.search(rest)
    school = school_m.group(0) if school_m else None
    degree_m = DEGREE_RE.search(rest)
    degree = degree_m.group(0) if degree_m else None
    major = rest
    for token in (school, degree):
        if token:
            major = major.replace(token, " ")
    major = re.sub(r"[\s|,，、:：]+", " ", major).strip() or None
    return {
        "school": school,
        "major": major,
        "degree": degree,
        "period": period,
        "description": " ".join(desc_lines) if desc_lines else None,
    }


def _parse_experience_entry(header: str, desc_lines: list[str]) -> dict:
    period, rest = _split_entry_header(header)
    parts = [p.strip() for p in re.split(r"\s{2,}|\s*\|\s*", rest) if p.strip()]
    company = role = None
    if len(parts) >= 2:
        company, role = parts[0], parts[1]
    elif parts:
        company_m = COMPANY_RE.search(parts[0]) or COMPANY_EN_RE.search(parts[0])
        role_m = ROLE_RE.search(parts[0]) or ROLE_EN_RE.search(parts[0])
        if company_m and role_m:
            company = company_m.group(0)
            role = role_m.group(0)
        elif " " in parts[0]:
            # 兜底：按第一个空格拆（项目条目常见"项目名 角色"结构）
            head, _, tail = parts[0].partition(" ")
            company, role = head.strip(), tail.strip() or None
        else:
            company = parts[0]
    return {
        "company": company,
        "role": role,
        "period": period,
        "description": " ".join(desc_lines) if desc_lines else None,
    }


def _parse_skills(lines: list[str]) -> list[str]:
    skills: list[str] = []
    for line in lines:
        text = SKILL_PREFIX_RE.sub("", line.strip())
        for token in re.split(r"[、,，/|·;；]|\s{2,}", text):
            token = ITEM_LEAD_RE.sub("", token).strip(" ：:;；-—")
            if token and len(token) <= 30 and token not in skills:
                skills.append(token)
    return skills


def structure_document(paragraphs: list[str], rule_version: str) -> StructureResult:
    """主入口：文本行 → 结构化简历 + 解析轨迹 + 未识别内容。"""
    result = StructureResult()
    consumed: set[int] = set()

    basic = {"name": None, "phone": None, "email": None, "city": None, "extra": {}}

    # ---------- 1. 基本信息（邮箱/电话/姓名/城市） ----------
    # 注意：同一行可能同时含电话与邮箱（"电话：138... 邮箱：a@b.com"），
    # 必须把所有能识别的字段都从该行取出，不能取到第一个就 continue——
    # 否则另一种联系方式会被静默丢弃（FR-03：严禁静默丢失）。
    for idx, line in enumerate(paragraphs[:8]):
        if idx in consumed:
            continue
        matched_any = False

        m = EMAIL_RE.search(line)
        if m and not basic["email"]:
            basic["email"] = m.group(0)
            matched_any = True
            result.trace.append(_trace("basic_info.email", m.group(0), line, "regex:email"))
        m = PHONE_RE.search(line) or PHONE_LANDLINE_RE.search(line)
        if m and not basic["phone"]:
            basic["phone"] = m.group(0)
            matched_any = True
            result.trace.append(_trace("basic_info.phone", m.group(0), line, "regex:phone"))
        m = CITY_RE.search(line)
        if m and not basic["city"] and len(line) <= 30:
            basic["city"] = m.group(0)
            matched_any = True
            result.trace.append(_trace("basic_info.city", m.group(0), line, "regex:city"))
        if matched_any:
            consumed.add(idx)
            continue

        m = NAME_LABEL_RE.match(line.strip())
        if m and not basic["name"]:
            basic["name"] = m.group(1)
            consumed.add(idx)
            result.trace.append(_trace("basic_info.name", m.group(1), line, "regex:name_label"))
            continue
        # 无标签姓名：前 3 行内的短纯中文行（2-4 字），且不是章节标题
        if (
            not basic["name"]
            and idx < 3
            and 2 <= len(line.strip()) <= 4
            and re.fullmatch(r"[一-龥]{2,4}", line.strip())
            and _detect_section(line) is None
        ):
            basic["name"] = line.strip()
            consumed.add(idx)
            result.trace.append(_trace("basic_info.name", basic["name"], line, "heuristic:short_cn_line"))
            continue
        # 英文姓名：前 2 行内、2-3 个英文词、不含联系信息
        if (
            not basic["name"]
            and idx < 2
            and re.fullmatch(r"[A-Za-z]+(?: [A-Za-z]+){1,2}", line.strip())
            and "@" not in line
        ):
            basic["name"] = line.strip()
            consumed.add(idx)
            result.trace.append(_trace("basic_info.name", basic["name"], line, "heuristic:en_name"))

    # ---------- 2. 章节切分 ----------
    sections: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    for idx, line in enumerate(paragraphs):
        if idx in consumed:
            continue
        section = _detect_section(line)
        if section:
            current = section
            consumed.add(idx)
            result.trace.append(
                _trace(f"section.{section}", section, line, f"keyword:{_normalize_title(line)}")
            )
            sections.setdefault(section, [])
            continue
        if current:
            sections.setdefault(current, []).append((idx, line))
            consumed.add(idx)

    # ---------- 3. 各章节解析 ----------
    education, experience, projects = [], [], []

    for idx, line in sections.get("education", []):
        if PERIOD_RE.search(line):
            education.append(_parse_education_entry(line, []))
            result.trace.append(_trace(f"education[{len(education)-1}]", line, line, "entry:period_split"))
        elif education and not _looks_like_prose(line):
            education[-1]["description"] = (
                (education[-1]["description"] or "") + " " + line
            ).strip()
        else:
            # 散文句或无条目可归属的行：交还未识别池（FR-03 严禁静默丢失）
            consumed.discard(idx)

    for idx, line in sections.get("experience", []):
        if PERIOD_RE.search(line):
            experience.append(_parse_experience_entry(line, []))
            result.trace.append(_trace(f"experience[{len(experience)-1}]", line, line, "entry:period_split"))
        elif experience and not _looks_like_prose(line):
            experience[-1]["description"] = (
                (experience[-1]["description"] or "") + " " + line
            ).strip()
        else:
            consumed.discard(idx)

    for idx, line in sections.get("projects", []):
        if PERIOD_RE.search(line):
            entry = _parse_experience_entry(line, [])
            # _parse_experience_entry 产出的是 company 键，而 ProjectItem 的契约是 name。
            # 不改这里的话，项目名会一直落在 company 上，前端读 item.name 只能显示"未识别"。
            if entry.get("company"):
                entry["name"] = entry.pop("company")
            projects.append(entry)
            result.trace.append(_trace(f"projects[{len(projects)-1}]", line, line, "entry:period_split"))
        elif projects and not _looks_like_prose(line):
            projects[-1]["description"] = (
                (projects[-1]["description"] or "") + " " + line
            ).strip()
        else:
            consumed.discard(idx)

    skills = _parse_skills([ln for _, ln in sections.get("skills", [])])
    for i, s in enumerate(skills):
        result.trace.append(_trace(f"skills[{i}]", s, s, "split:delimiters"))

    honors = []
    for idx, line in sections.get("honors", []):
        text = ITEM_LEAD_RE.sub("", line).strip()
        if text and not _looks_like_prose(text):
            honors.append(text)
            result.trace.append(_trace(f"honors[{len(honors)-1}]", text, line, "line:one_per_line"))
        else:
            # 散文式内容（如个人介绍）不算荣誉，交还给未识别池（FR-03）
            consumed.discard(idx)

    # 未归类区块：显式声明"这里的内容机器读不了"，
    # 原样交还未识别池而不是塞进上一个章节——否则导出再解析时
    # 这些内容会被静默改判成荣誉/经历，ATS 对比结论就此失真。
    for idx, line in sections.get("other", []):
        consumed.discard(idx)

    result.structure = {
        "basic_info": basic,
        "education": education,
        "experience": experience,
        "projects": projects,
        "skills": skills,
        "honors": honors,
    }

    # ---------- 4. 未识别内容（FR-03：严禁静默丢失） ----------
    for idx, line in enumerate(paragraphs):
        if idx not in consumed:
            result.unrecognized.append(
                {"text": line, "reason": "无法归入已知字段（不在任何已识别章节内）"}
            )

    return result


def _looks_like_prose(text: str) -> bool:
    """自由散文的判定：含句号的完整句子。

    只以句号为特征是保守取舍——经历描述的 bullet 行通常不含句号；
    宁可把边界内容并入字段描述（内容未丢失），也不把正常 bullet 误判为未识别。
    """
    return "。" in text


def _trace(field_name: str, extracted: str, source: str, rule: str) -> dict:
    return {
        "field": field_name,
        "extracted": extracted,
        "source_region": _clean_snippet(source),
        "rule_applied": rule,
        "verdict": "parsed",
    }
