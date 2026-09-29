"""诊断规则库（设计文档测试策略第 4 条：诊断规则配置化）。

规则集中于此而非散落在各模块内部，目的是让测试用例可以**系统枚举**——
每条规则对应一组用例，规则变更时回归范围明确。
"""
import re

# ---------- 标点（FR-04 中英文标点混用） ----------
CN_PUNCT = "，。；：？！、（）"
EN_PUNCT = ",;:?!()"

# ---------- 日期（FR-04 日期格式不一致 / 时间线倒序 / 时间断层） ----------
# 支持 2021.09 / 2021/09 / 2021-09 / 2021年9月 四种写法
DATE_TOKEN = r"(?:\d{4}[./\-年]\d{1,2}月?|\d{4}[./\-]\d{1,2})"
PERIOD_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:[-—~至到]|到|至)\s*(?P<end>{DATE_TOKEN}|至今|现在|now|present)",
    re.IGNORECASE,
)

# 日期标准化：取出年、月，便于比较与断层计算
_YM_RE = re.compile(r"(?P<y>\d{4})\D?(?P<m>\d{1,2})")


def parse_year_month(token: str) -> tuple[int, int] | None:
    """把 2021.09 / 2021年9月 / 2021-09 统一解析为 (年, 月)。"""
    m = _YM_RE.search(token)
    if not m:
        return None
    return int(m.group("y")), int(m.group("m"))


def period_months(period: str | None) -> tuple[tuple[int, int] | None, tuple[int, int] | None, bool]:
    """解析时间段，返回 (起始, 结束, 是否进行中)。

    结束为 None 表示"至今"等开放式表述；进行中标志用于避免把在职状态误判为断层。
    """
    if not period:
        return None, None, False
    m = PERIOD_RE.search(period)
    if not m:
        return None, None, False
    start = parse_year_month(m.group("start"))
    end_token = m.group("end")
    ongoing = bool(re.fullmatch(r"至今|现在|now|present", end_token, re.IGNORECASE))
    end = None if ongoing else parse_year_month(end_token)
    return start, end, ongoing


def month_diff(a: tuple[int, int], b: tuple[int, int]) -> int:
    """b - a 的月份差。"""
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


# 时间断层阈值：相邻经历间隔超过此月数提示（设计未定具体值，取 6 个月并在证据中说明）
GAP_MONTHS = 6

# ---------- 无关个人信息（FR-04） ----------
IRRELEVANT_PERSONAL_INFO = [
    ("性别", re.compile(r"性\s*别\s*[:：]")),
    ("年龄", re.compile(r"年\s*龄\s*[:：]")),
    ("民族", re.compile(r"民\s*族\s*[:：]")),
    ("政治面貌", re.compile(r"政治面貌|籍\s*贯")),
    ("婚姻状况", re.compile(r"婚姻|未\s*婚|已\s*婚")),
    ("身高体重", re.compile(r"身\s*高|体\s*重|血\s*型")),
    ("星座", re.compile(r"星\s*座|生\s*肖")),
]

# ---------- 联系方式（FR-04） ----------
# 11 位数字但不是合法号段 → 疑似输错；带分隔符的固话单独识别
SUSPECT_MOBILE_RE = re.compile(r"(?<!\d)(1\d{10})(?!\d)")
VALID_MOBILE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
EMAIL_SHAPE_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w.]+)?")
EMAIL_VALID_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[A-Za-z]{2,}$")

# ---------- 错别字 / 病句启发式（FR-04） ----------
COMMON_TYPOS = {
    "的的": "的",
    "了了": "了",
    "在在": "在",
    "是是": "是",
    "和和": "和",
    "与与": "与",
    "从从": "从",
    "为为": "为",
    "对对": "对",
    "并并": "并",
}
# 明显影响专业感的错别字（形近/音近误用）
TYPO_WORDS = [
    ("既使", "即使"),
    ("按装", "安装"),
    ("部置", "部署"),
    ("效律", "效率"),
    ("数据库据", "数据库"),
    ("并并", "并"),
    ("运维维", "运维"),
    ("测试试", "测试"),
]
# 描述行过短 → 信息量不足，视为病句式表达
MIN_DESC_LENGTH = 12

# ---------- 空话套话与弱表达（FR-05） ----------
CLICHE_PHRASES = [
    "吃苦耐劳",
    "抗压能力强",
    "有团队精神",
    "善于沟通",
    "学习能力强",
    "工作认真负责",
    "积极主动",
    "有责任心",
    "性格开朗",
    "团结同事",
    "执行力强",
    "有上进心",
    "服从安排",
    "认真踏实",
]
WEAK_PHRASES = [
    "参与了",
    "协助了",
    "负责了",
    "帮助了",
    "跟随",
    "跟着",
    "一起完成",
    "做了一些",
    "参与了一些",
]
# 强动词：出现即说明表达有力度
STRONG_VERBS = [
    "设计", "搭建", "重构", "主导", "独立完成", "实现", "优化", "推动",
    "落地", "上线", "压缩", "提升", "降低", "建立", "制定", "完成", "开发",
    "部署", "迁移", "治理", "自动化",
]

# ---------- 量化（FR-05） ----------
QUANT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|万|千|百|亿|人|次|天|小时|个|条|倍|ms|s|QPS|TPS|GB|MB)"
    r"|(?<!\d)\d{3,}(?!\d)"
)

# ---------- 要素完整性（FR-05：做了什么 / 怎么做 / 结果如何） ----------
# "怎么做"信号：技术名词、工具名、方法论
# 注意：不能收"接口/框架/自动化"这类宽泛词——"负责接口开发"说的是"做了什么"而非"怎么做"
METHOD_SIGNALS = [
    "使用", "采用", "基于", "通过", "借助", "利用", "依托", "运用",
    "Python", "Java", "Go", "Vue", "React", "SQL", "MySQL", "Redis",
    "Docker", "K8s", "Kubernetes", "FastAPI", "Django", "Spring",
    "脚本", "算法", "模型", "工具链", "中间件", "队列", "缓存",
]
# "做了什么"信号：动作动词
ACTION_SIGNALS = [
    "设计", "开发", "搭建", "实现", "优化", "重构", "维护", "部署", "测试",
    "分析", "整理", "撰写", "统筹", "推进", "支持", "排查", "修复", "上线",
    "组织", "带领", "跟进", "采集", "制作", "输出", "落地", "复现", "验证",
    "保障", "协助", "完成", "编写", "制定", "搭建", "运维", "交付", "推广",
]
# "结果如何"信号：完成 / 达成 / 提升 等结果导向词
RESULT_SIGNALS = [
    "完成", "达成", "实现", "提升", "降低", "缩短", "减少", "提高", "覆盖",
    "通过", "获得", "输出", "沉淀", "形成", "落地",
]

# ---------- ATS 适配（FR-06）：机器读取风险的排版特征 ----------
# 图标 / emoji 代替文字：ATS 通常读不出图标承载的信息
ICON_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿️✀-➿]")
# 特殊字符装饰（ATS 易读乱）
DECORATION_RE = re.compile(r"[★☆◆●○◎◇■□▲△※§±×÷]")
# 双栏/表格排版的痕迹（文本层难以直接判定，用制表符与连续空格作启发）
MULTI_COLUMN_HINT_RE = re.compile(r"\t|\s{4,}")

# ---------- 岗位匹配（FR-08） ----------
# JD 中常见的要求描述句式，用于抽取关键要求
JD_REQUIREMENT_SPLIT_RE = re.compile(r"[\n;；]|\d+[.、)）]")
JD_NOISE_RE = re.compile(
    r"^(?:职位描述|岗位职责|任职要求|岗位要求|任职资格|职位要求|我们希望你|加分项|职责描述|工作内容)[:：]?\s*$"
)
# JD 中的硬技能关键词（出现即视为可匹配项）
JD_SKILL_KEYWORDS = [
    "Python", "Java", "Go", "Golang", "C++", "JavaScript", "TypeScript", "Vue",
    "React", "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB", "Docker",
    "Kubernetes", "K8s", "Linux", "Git", "FastAPI", "Django", "Spring",
    "SpringBoot", "Spring Boot", "Flask", "Pandas", "Spark", "Flink", "Kafka",
    "测试", "自动化测试", "性能测试", "接口测试", "CI/CD", "DevOps",
    "数据分析", "机器学习", "深度学习", "NLP", "爬虫", "微服务",
    "项目管理", "Axure", "Figma", "PS", "Excel",
]
# JD 中的软素质关键词
JD_SOFT_KEYWORDS = [
    "沟通", "团队", "协作", "抗压", "学习能力", "责任心", "积极主动",
    "英语", " CET", "CET", "文档能力", "逻辑", "细致",
]
# 学历要求（用于与简历比对）
DEGREE_LEVELS = {
    "大专": 1, "专科": 1, "大专/专科": 1,
    "本科": 2, "学士": 2, "Bachelor": 2,
    "硕士": 3, "研究生": 3, "Master": 3,
    "博士": 4, "PhD": 4, "博士后": 5,
}
