"""改动点计算与语义指纹（设计文档 4.5.2 / 4.5.4 / 4.5.7 #2）。

ChangePoint 是 O-02「新旧对照」的最小单位，也是风险分级（O-07）与
测试分类断言的依据。设计文档特别强调：**改动点不是"日志"，而是可被程序
消费的结构化数据**——这是让"改写质量"可测的关键。

`change_class` 一个字段同时支撑三件事：
  前端高亮不同颜色的改动（产品）｜ 判定风险等级（O-07）｜ 测试用例分类断言（测试）
"""
import difflib
import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.diagnosis import rules

# 改动类型
CHANGE_REPLACE = "replace"
CHANGE_INSERT = "insert"
CHANGE_DELETE = "delete"

# 改动性质
CLASS_PUNCTUATION = "punctuation"  # 标点
CLASS_TYPO = "typo"                # 错别字
CLASS_FORMAT = "format"            # 日期格式 / 空格 / 全半角
CLASS_WORDING = "wording"          # 措辞
CLASS_STRUCTURE = "structure"      # 语序 / 结构

# O-06 确定性修正的可自动应用类别（不改变语义）
SAFE_CLASSES = {CLASS_PUNCTUATION, CLASS_TYPO, CLASS_FORMAT}

CLASS_LABELS = {
    CLASS_PUNCTUATION: "标点",
    CLASS_TYPO: "错别字",
    CLASS_FORMAT: "格式规范",
    CLASS_WORDING: "措辞",
    CLASS_STRUCTURE: "结构",
}

_ALL_PUNCT = set(rules.CN_PUNCT) | set(rules.EN_PUNCT) | {
    "，", "。", "；", "：", "？", "！", "、", "（", "）",
    ",", ".", ";", ":", "?", "!", "·", "—", "…", "“", "”", "‘", "’",
}


@dataclass
class ChangePoint:
    """单个改动点（设计文档 4.5.2）。"""

    change_type: str            # replace | insert | delete
    before_span: tuple[int, int]
    after_span: tuple[int, int]
    before_text: str
    after_text: str
    change_class: str           # punctuation | typo | format | wording | structure

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type,
            "before_span": list(self.before_span),
            "after_span": list(self.after_span),
            "before_text": self.before_text,
            "after_text": self.after_text,
            "change_class": self.change_class,
            "change_class_label": CLASS_LABELS.get(self.change_class, self.change_class),
        }


def _strip_punct(text: str) -> str:
    """去掉标点与空白，用于判断"是否只是书写规范差异"。

    空格一并去除："," → "，" 这类改动本质是标点规范化，
    若因附带一个空格就被判成 format，前端会把改动高亮成错误的颜色。
    """
    return "".join(ch for ch in text if ch not in _ALL_PUNCT and not ch.isspace())


def _to_halfwidth(text: str) -> str:
    """全角字母数字与空格转半角（NFKC 会把中文标点也转，故只做定向替换）。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _normalize_dates(text: str) -> str:
    """日期写法归一化：2021.09 / 2021/09 / 2021年9月 → 202109。"""
    return re.sub(
        r"(\d{4})\s*[./\-年]\s*(\d{1,2})\s*月?",
        lambda m: f"{m.group(1)}{int(m.group(2)):02d}",
        text,
    )


def normalize_for_fingerprint(text: str) -> str:
    """语义指纹用的规范化：抹除所有"不改变语义"的书写差异。

    覆盖：全半角、空格、标点、日期写法、已知错别字。
    规范化后若两端一致，说明改动未触及语义。
    """
    s = _to_halfwidth(text or "")
    s = _normalize_dates(s)
    s = _strip_punct(s)
    s = re.sub(r"\s+", "", s)
    for wrong, right in rules.COMMON_TYPOS.items():
        s = s.replace(wrong, right)
    for wrong, right in rules.TYPO_WORDS:
        s = s.replace(wrong, right)
    return s


def semantic_fingerprint(text: str) -> str:
    """语义指纹：规范化文本的短哈希，用于前后语义一致性比对。"""
    normalized = normalize_for_fingerprint(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _classify_change(
    before_text: str, after_text: str, before_full: str = "", after_full: str = ""
) -> str:
    """判定单处改动的性质。

    优先级从保守到激进：只要能归入"不改变语义"的类别就归入；
    归不进去的一律 wording（保守优先，设计文档 4.5.4 硬约束 1）。

    注意必须传入整句文本：字符级 diff 会把"既使→即使"切成"既→即"这种
    单字片段，脱离上下文后既看不出是错别字、也看不出是日期格式改写。
    因此先做**整句级**语义指纹判定，再细分到点。
    """
    # 1. 纯标点差异
    if _strip_punct(before_text) == _strip_punct(after_text):
        return CLASS_PUNCTUATION

    # 2. 整句字符组成相同、顺序不同 → 语序重排。
    #    必须放在指纹判定之前：字符级 diff 会把"Python 与 Java"→"Java 与 Python"
    #    切成若干跨位置的 replace 片段，逐点看不出是重排。
    if (
        before_full
        and after_full
        and before_full != after_full
        and sorted(before_full) == sorted(after_full)
    ):
        return CLASS_STRUCTURE

    # 3. 整句语义指纹一致 → 必属规范类，再细分是错别字还是格式
    if before_full and after_full and semantic_fingerprint(before_full) == semantic_fingerprint(after_full):
        for wrong, right in rules.TYPO_WORDS:
            if wrong in before_full or wrong in after_full or right in before_full or right in after_full:
                return CLASS_TYPO
        if any(w in before_full or w in after_full for w in rules.COMMON_TYPOS):
            return CLASS_TYPO
        return CLASS_FORMAT

    # 4. 片段级已知错别字修正
    for wrong, right in rules.TYPO_WORDS:
        if (wrong in before_text and right in after_text) or (
            wrong in after_text and right in before_text
        ):
            return CLASS_TYPO
    for wrong, right in rules.COMMON_TYPOS.items():
        if wrong in before_text or wrong in after_text:
            return CLASS_TYPO

    # 5. 格式规范（空格 / 全半角 / 日期写法）
    if normalize_for_fingerprint(before_text) == normalize_for_fingerprint(after_text):
        return CLASS_FORMAT

    # 6. 片段级语序重排
    if before_text and after_text and sorted(before_text) == sorted(after_text):
        return CLASS_STRUCTURE

    # 7. 其余一律视为措辞改动
    return CLASS_WORDING


def compute_change_points(before: str, after: str) -> list[ChangePoint]:
    """用字符级 diff 计算逐点改动（O-02 的最小单位）。

    逐点而非整段替换——设计文档明确要求"标出具体改动点，而非整段替换让用户自行比对"。
    """
    before = before or ""
    after = after or ""
    if before == after:
        return []

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    points: list[ChangePoint] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        b_text = before[i1:i2]
        a_text = after[j1:j2]
        change_type = {
            "replace": CHANGE_REPLACE,
            "delete": CHANGE_DELETE,
            "insert": CHANGE_INSERT,
        }[tag]
        points.append(
            ChangePoint(
                change_type=change_type,
                before_span=(i1, i2),
                after_span=(j1, j2),
                before_text=b_text,
                after_text=a_text,
                change_class=_classify_change(b_text, a_text, before, after),
            )
        )
    return points


def unsafe_change_rate(change_points: list[ChangePoint]) -> float:
    """非目标语句之外的改动占比线索：不安全类别改动点占比（0-1）。

    测试可断言"仅修正标点的改写，该值必须为 0"。
    """
    if not change_points:
        return 0.0
    unsafe = sum(1 for c in change_points if c.change_class not in SAFE_CLASSES)
    return round(unsafe / len(change_points), 4)
