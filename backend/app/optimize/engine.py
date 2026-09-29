"""改写引擎（O-01 单条建议改写，设计文档 4.5.1 五步链路）。

引擎接口化，AI 接入点已按「接口 + 桩替换」预留：
  RuleRewriteEngine —— 确定性规则版，只做**不改变语义**的确定性修正；
  AIRewriteEngine   —— 调用用户自带模型（OpenAI 兼容端点），见 ai_engine.py；
  AIStubEngine      —— 模拟一个"会编造"的模型，用于验证降级路径。

五步链路中，② 前置抽事实 与 ④ 后置抽事实比对由基类统一执行，
各引擎只负责第 ③ 步"生成候选文本"——这样**事实守恒校验不可能被某个引擎绕过**。

关键取舍（设计文档原文）：**宁可改写失败，也不返回可能编造的内容。**
检测到事实违反时默认行为是拒绝输出，而不是"提示用户注意"——
本项目的用户是没有经验的求职者，把可能编造的内容显示出来再附一句警告，
实际风险远大于"告诉用户这段改不了"。
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.diagnosis import rules
from app.optimize.changes import (
    ChangePoint,
    compute_change_points,
)
from app.optimize.facts import FactCheckReport, compare_facts
from app.optimize.risk import RISK_AUTO_SAFE, RiskGrade, grade_risk

# 改写状态
STATUS_GENERATED = "generated"        # 产出可采纳的改写
STATUS_SUGGESTION_ONLY = "suggestion_only"  # 降级为仅建议（FR-12 只读展示）
STATUS_REJECTED = "rejected"          # 事实违反，拒绝输出

STATUS_LABELS = {
    STATUS_GENERATED: "已生成改写",
    STATUS_SUGGESTION_ONLY: "仅建议",
    STATUS_REJECTED: "已拒绝",
}

# 规则版引擎可确定性处理的类别（其余一律降级为仅建议，不编造）
RULE_ENGINE_VERSION = "rule-rewrite-1.0.0"
AI_STUB_VERSION = "ai-stub-1.0.0"
AI_WORDING_STUB_VERSION = "ai-wording-stub-1.0.0"

_CN_PUNCT_MAP = {",": "，", ";": "；", ":": "：", "?": "？", "!": "！"}
_DATE_TARGETS = {
    "dot": ("{y}.{m:02d}", re.compile(r"\d{4}\.\d{1,2}")),
    "slash": ("{y}/{m:02d}", re.compile(r"\d{4}/\d{1,2}")),
    "dash": ("{y}-{m:02d}", re.compile(r"\d{4}-\d{1,2}")),
    "cn": ("{y}年{m}月", re.compile(r"\d{4}年\d{1,2}月")),
}


def _is_cn(ch: str) -> bool:
    return bool(ch) and "一" <= ch <= "龥"


@dataclass
class RewriteRequest:
    """一次改写请求（来自某条具体问题项）。"""

    issue: dict                     # 问题项（含 category / location / problem / suggestion）
    field_name: str                 # 目标字段，如 "experience[0].description"
    field_text: str = ""            # 该字段当前完整文本
    dominant_date_format: str = "dot"  # 全文主导日期写法


@dataclass
class RewriteOutcome:
    """改写产出（含事实比对报告与风险等级）。"""

    status: str
    before: str
    after: str
    change_points: list[ChangePoint] = field(default_factory=list)
    fact_check: FactCheckReport | None = None
    risk: RiskGrade | None = None
    model_version: str = ""
    reproducible: bool = True
    reason: str = ""
    issue_id: str = ""

    @property
    def risk_level(self) -> str:
        return self.risk.risk_level if self.risk else ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "before": self.before,
            "after": self.after,
            "change_points": [c.to_dict() for c in self.change_points],
            "fact_check": self.fact_check.to_dict() if self.fact_check else None,
            "risk_level": self.risk_level,
            "risk": self.risk.to_dict() if self.risk else None,
            "model_version": self.model_version,
            "reproducible": self.reproducible,
            "reason": self.reason,
            "issue_id": self.issue_id,
        }


class RewriteEngine(ABC):
    """改写引擎基类：统一执行前置抽事实 → 生成 → 后置比对 → 改动点计算 → 分级。"""

    name: str = ""
    version: str = ""
    # 相同输入是否得到相同结论（NFR-08 约束的是确定性引擎）。
    # AI 引擎受采样影响，子类覆盖为 False，让记录如实标注而不是假装可复现。
    reproducible: bool = True

    @abstractmethod
    def _generate(self, req: RewriteRequest) -> tuple[str | None, str]:
        """生成候选改写文本。返回 (改写后文本 or None, 说明)。

        返回 None 表示"这段改不了"——调用方会降级为仅建议，不会编造内容。
        """

    def rewrite(self, req: RewriteRequest) -> RewriteOutcome:
        before = (req.field_text or "").strip()
        issue_id = str(req.issue.get("issue_id") or "")

        # ① 前置抽取：改写前的事实清单
        facts_before = compare_facts(before, before)

        # ③ 生成候选
        candidate, note = self._generate(req)
        if candidate is None:
            # 无法安全改写 → 降级为仅建议（FR-12 只读展示），不产出改写文本
            return RewriteOutcome(
                status=STATUS_SUGGESTION_ONLY,
                before=before,
                after="",
                model_version=self.version,
                reproducible=self.reproducible,
                reason=note or "该问题无法由规则安全改写，请按建议手动修改",
                issue_id=issue_id,
            )

        after = candidate.strip()
        if after == before:
            return RewriteOutcome(
                status=STATUS_SUGGESTION_ONLY,
                before=before,
                after="",
                model_version=self.version,
                reproducible=self.reproducible,
                reason="未产生实际改动",
                issue_id=issue_id,
            )

        # ④ 后置比对：抽取改写后事实，与前置逐项比对
        fact_check = compare_facts(before, after)
        if not fact_check.passed:
            # 事实违反 → 拒绝输出。这是本模块最重要的兜底。
            violated = [f"{f['kind']}:{f['value']}" for f in fact_check.violated]
            added = [f"{f['kind']}:{f['value']}" for f in fact_check.added]
            return RewriteOutcome(
                status=STATUS_REJECTED,
                before=before,
                after="",
                fact_check=fact_check,
                model_version=self.version,
                reproducible=self.reproducible,
                reason=(
                    "改写会改变或新增原文没有的事实，已拒绝输出"
                    f"（被改变：{'、'.join(violated) or '无'}；新增：{'、'.join(added) or '无'}）"
                ),
                issue_id=issue_id,
            )

        # ⑤ 改动点计算 + 风险分级
        change_points = compute_change_points(before, after)
        risk = grade_risk(before, after, change_points)
        # 前置事实清单回填（避免额外一次抽取的浪费）
        fact_check.facts_before = facts_before.facts_before

        return RewriteOutcome(
            status=STATUS_GENERATED,
            before=before,
            after=after,
            change_points=change_points,
            fact_check=fact_check,
            risk=risk,
            model_version=self.version,
            reproducible=self.reproducible,
            reason=note,
            issue_id=issue_id,
        )


# ---------- 确定性修正函数（可单独测试） ----------

def fix_mixed_punctuation(text: str) -> str:
    """中文语境下的英文标点转中文标点。

    只在前后任意一侧为中文时才替换，避免破坏 CI/CD、3.6/4.0、版本号这类合法英文标点。
    转成中文标点后紧随的空格要一并吃掉——中文标点本身已承担间隔，留空格会出现"开发， 使用"。
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < n else ""
        if ch in _CN_PUNCT_MAP and (_is_cn(prev) or _is_cn(nxt)):
            out.append(_CN_PUNCT_MAP[ch])
            # 吞掉紧随其后的一个空格
            i += 2 if nxt == " " else 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def fix_typos(text: str) -> str:
    for wrong, right in rules.TYPO_WORDS:
        text = text.replace(wrong, right)
    for wrong, right in rules.COMMON_TYPOS.items():
        text = text.replace(wrong, right)
    return text


def fix_date_format(text: str, target: str = "dot") -> str:
    """把全文日期统一为一种写法（默认 2021.09）。"""
    fmt, _ = _DATE_TARGETS.get(target, _DATE_TARGETS["dot"])

    def repl(m: re.Match) -> str:
        y, mo = m.group(1), int(m.group(2))
        return fmt.format(y=y, m=mo)

    return re.sub(r"(\d{4})\s*[./\-年]\s*(\d{1,2})\s*月?", repl, text)


def fix_decorations(text: str) -> str:
    """删除装饰符号与图标（ATS 读不出其语义，只产生乱码）。"""
    return rules.DECORATION_RE.sub("", rules.ICON_RE.sub("", text))


def fix_spacing(text: str) -> str:
    """全角空格转半角、压缩连续空格。"""
    text = text.replace("　", " ")
    return re.sub(r" {2,}", " ", text)


# category → 修正函数（规则版引擎的能力边界）
_CATEGORY_FIXERS = {
    "中英文标点混用": lambda text, req: fix_mixed_punctuation(text),
    "错别字": lambda text, req: fix_typos(text),
    "日期格式不一致": lambda text, req: fix_date_format(text, req.dominant_date_format),
    "ATS·装饰字符": lambda text, req: fix_decorations(text),
    "ATS·图标信息": lambda text, req: fix_decorations(text),
    "时间线倒序": lambda text, req: None,
}


class RuleRewriteEngine(RewriteEngine):
    """规则版改写引擎：只做确定性、不改变语义的修正。

    对"要素缺失 / 量化缺失 / 空话套话 / 技能缺失"这类需要补充真实信息的问题，
    一律返回 None（降级为仅建议）——**规则引擎不替用户编造经历**。
    """

    name = "rule_rewrite"
    version = RULE_ENGINE_VERSION

    def _generate(self, req: RewriteRequest) -> tuple[str | None, str]:
        category = req.issue.get("category") or ""
        text = req.field_text or ""
        fixer = _CATEGORY_FIXERS.get(category)
        if fixer is None:
            return None, f"「{category}」需要补充真实信息，规则引擎不代写，请按建议手动修改"
        fixed = fixer(text, req)
        if fixed is None or fixed == text:
            return None, f"「{category}」未找到可自动修正的内容，请手动处理"
        return fixed, f"按「{category}」规则确定性修正"


class AIStubEngine(RewriteEngine):
    """AI 桩引擎：用于验证降级路径与事实守恒校验是否真的生效。

    它故意做两类事：
      1. fabricate=True  把文本中的数字改大（模拟模型编造业绩）
      2. fabricate=False 只做同义标点规范化（模拟"守规矩"的模型）

    测试用第 1 类验证"系统确实拒绝输出并降级为仅建议，而不是把违规内容透出去"。
    """

    name = "ai_stub"
    version = AI_STUB_VERSION

    def __init__(self, fabricate: bool = False):
        self.fabricate = fabricate

    def _generate(self, req: RewriteRequest) -> tuple[str | None, str]:
        text = req.field_text or ""
        if self.fabricate:
            # 模拟幻觉：把"10 万"改成"500 万"这类无依据的放大
            inflated = re.sub(
                r"(\d+(?:\.\d+)?)\s*(万|千|百|%|％)",
                lambda m: f"{int(float(m.group(1)) * 50)}{m.group(2)}",
                text,
            )
            if inflated != text:
                return inflated, "桩引擎：模拟模型放大业绩数据"
            return text + "，并获得一致好评", "桩引擎：模拟模型添加无依据内容"
        return fix_mixed_punctuation(fix_typos(text)), "桩引擎：仅做规范类修正"


class WordingStubEngine(RewriteEngine):
    """做同义措辞改写的 AI 桩：事实守恒，但改变表达方式。

    规则引擎只做确定性修正（产物恒为 auto_safe），因此**无法凭自身验证
    O-07 的分界线**——needs_review 必须由"会改措辞的引擎"产出才可测。
    这个桩就是为那条分界线而存在的测试夹具。
    """

    name = "ai_wording_stub"
    version = AI_WORDING_STUB_VERSION

    # 同义强化替换对：不触碰任何可抽取事实（数字/学校/技术名词都不变）
    _SUBSTITUTIONS = {"负责": "主导", "参与": "主力完成", "使用": "基于"}

    # 这些类别属于"确定性修正"，桩也按安全路径处理，
    # 于是一次注入即可同时产出 auto_safe 与 needs_review 两类改写。
    _SAFE_CATEGORIES = {
        "中英文标点混用",
        "错别字",
        "日期格式不一致",
        "ATS·装饰字符",
        "ATS·图标信息",
    }

    def _generate(self, req: RewriteRequest) -> tuple[str | None, str]:
        text = req.field_text or ""
        if (req.issue.get("category") or "") in self._SAFE_CATEGORIES:
            fixed = fix_mixed_punctuation(fix_typos(text))
            if fixed != text:
                return fixed, "桩引擎：规范类修正"
            return None, "桩引擎：未找到可自动修正的内容"

        out = text
        for src, dst in self._SUBSTITUTIONS.items():
            if src in out:
                out = out.replace(src, dst)
                break
        if out == text:
            return None, "桩引擎：未找到可同义改写的词"
        return out, "桩引擎：同义措辞强化（事实守恒但改变表达）"


# 默认引擎（规则版优先，AI 桩可通过配置替换）
DEFAULT_ENGINE = RuleRewriteEngine()
