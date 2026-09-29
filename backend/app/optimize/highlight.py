"""FR-09 引导式亮点挖掘（纯逻辑层：无数据库、无服务依赖，可独立单测 —— NFR-07）。

产品语义（需求原文）：
  "通过逐层追问帮用户从平淡经历中拆解出可写的成果点，**由用户确认后**才写入。"

三条设计红线，全部有对应测试：

1. **只用用户提供的事实**。合成文本的事实必须全部来自「原文 + 用户答案」，
   比对不通过则拒绝输出（6002）——与改写引擎同一套 NFR-09 纪律，
   本模块不因为是"用户参与"就放松校验。
2. **未经确认不写入**。compose 只产预览；confirm 才落库，中间无任何隐式持久化。
3. **可跳过，不逼编造**。任何一层都可以跳过；跳过的层不计入合成，
   只在 missing_layers 里提示"还可以更好"，绝不替用户补内容。

与改写引擎的分工：改写（O-01）重组**原文已有**的事实；亮点挖掘（FR-09）
在用户显式授权下引入**用户新提供**的事实。两者的边界由事实比对的
"允许集合"体现——改写的允许集合只有原文，挖掘的允许集合是原文 + 答案。
"""
from dataclasses import dataclass

from app.diagnosis import rules
from app.optimize.facts import FactCheckReport, compare_facts

# ---------- 追问层（顺序即叙述顺序：做了什么 → 规模/数据 → 结果 → 佐证） ----------
LAYER_ACTION = "action"
LAYER_QUANT = "quant"
LAYER_RESULT = "result"
LAYER_EVIDENCE = "evidence"

LAYER_ORDER = [LAYER_ACTION, LAYER_QUANT, LAYER_RESULT, LAYER_EVIDENCE]

LAYER_LABELS = {
    LAYER_ACTION: "动作",
    LAYER_QUANT: "量化",
    LAYER_RESULT: "结果",
    LAYER_EVIDENCE: "佐证",
}

# 段落来源标注（original = 原文保留，其余 = 用户该层答案）
SOURCE_ORIGINAL = "original"

# 经历类区块（FR-09 的挖掘对象就是"经历"）
SECTION_LABELS = {"experience": "实习经历", "projects": "项目经历"}


@dataclass
class Question:
    """一层追问：问什么、为什么问、怎么答（示例降低用户的回答成本）。"""

    layer: str
    label: str
    question: str
    hint: str
    example: str
    needed: bool    # True = 原文缺这个要素，建议回答；False = 可选加分
    optional: bool  # True = 可跳过且不产生缺失提示

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "label": self.label,
            "question": self.question,
            "hint": self.hint,
            "example": self.example,
            "needed": self.needed,
            "optional": self.optional,
        }


@dataclass
class ComposeResult:
    """合成预览（不落库）：before/after、分段来源、事实比对、仍缺失的层。"""

    status: str  # composed | rejected
    before: str
    after: str
    segments: list[dict]
    fact_check: dict
    missing_layers: list[str]
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "before": self.before,
            "after": self.after,
            "segments": self.segments,
            "fact_check": self.fact_check,
            "missing_layers": self.missing_layers,
            "reason": self.reason,
        }


def field_label(field_name: str) -> str:
    """experience[0].description → 实习经历 · 第 1 条（用于界面标识挖掘对象）。"""
    section = field_name.split("[")[0]
    label = SECTION_LABELS.get(section, section)
    if "[" in field_name:
        try:
            idx = int(field_name.split("[")[1].split("]")[0])
            return f"{label} · 第 {idx + 1} 条"
        except (ValueError, IndexError):
            pass
    return label


def _strip_weak_prefix(text: str) -> str:
    """剥掉句首的弱参与表述（参与了/协助了/跟随…）。

    仅当用户在"动作"层给出了更强的表述时才执行——那是用户的显式授权，
    不违反"不改事实"红线（弱词不是事实，是表达力度问题）。
    """
    stripped = text.lstrip()
    for weak in rules.WEAK_PHRASES:
        if stripped.startswith(weak):
            return stripped[len(weak):].lstrip("，,。；; ")
    return text


def _norm(text: str) -> str:
    """去首尾标点的规范化形式，用于重复判定。"""
    return (text or "").strip().strip("，,。；;！!？?、 ")


def build_questions(original: str) -> list[Question]:
    """按原文缺失的要素生成追问序列（顺序固定：动作 → 量化 → 结果 → 佐证）。

    要素判定与 FR-05 内容质量诊断使用同一套信号词，保证"诊断说缺什么"
    与"挖掘就问什么"口径一致。
    """
    desc = (original or "").strip()
    has_action = any(k in desc for k in rules.ACTION_SIGNALS)
    has_quant = bool(rules.QUANT_RE.search(desc))
    has_result = any(k in desc for k in rules.RESULT_SIGNALS) or has_quant
    # 句首弱参与表述（参与了/协助了/跟随…）也要问"动作"——它是最典型的平淡点，
    # 用户答完后才有授权剥掉弱词（见 compose 的 _strip_weak_prefix）
    has_weak_prefix = any(desc.startswith(w) for w in rules.WEAK_PHRASES)

    questions: list[Question] = []
    if not has_action or has_weak_prefix:
        questions.append(
            Question(
                layer=LAYER_ACTION,
                label=LAYER_LABELS[LAYER_ACTION],
                question="在这段经历里，你具体负责做了什么？",
                hint="用一个明确的动作开头（设计 / 开发 / 搭建 / 优化 / 组织…），说清你负责的范围",
                example="例：负责订单模块的接口设计与开发",
                needed=True,
                optional=False,
            )
        )
    if not has_quant:
        questions.append(
            Question(
                layer=LAYER_QUANT,
                label=LAYER_LABELS[LAYER_QUANT],
                question="这件事涉及哪些可以量化的信息？",
                hint="数量、比例、耗时、规模都可以——数字让平淡的经历变具体",
                example="例：覆盖 3 条业务线、日均 10 万次调用、耗时从 2 小时缩短到 20 分钟",
                needed=True,
                optional=False,
            )
        )
    if not has_result:
        questions.append(
            Question(
                layer=LAYER_RESULT,
                label=LAYER_LABELS[LAYER_RESULT],
                question="这件事最终带来了什么结果？",
                hint="产出物或影响都可以（上线 / 覆盖 / 通过 / 获得…）；能量化更好",
                example="例：接口错误率降至 0.3%，通过全量验收并上线",
                needed=True,
                optional=False,
            )
        )
    questions.append(
        Question(
            layer=LAYER_EVIDENCE,
            label=LAYER_LABELS[LAYER_EVIDENCE],
            question="有没有可以佐证的产出或评价？（可跳过）",
            hint="文档、链接、竞赛名次、他人评价——有就写，没有可跳过",
            example="例：输出接口文档 1 份，获校级程序设计竞赛一等奖",
            needed=False,
            optional=True,
        )
    )
    return questions


def verify_facts(original: str, answers: dict[str, str], after_text: str) -> FactCheckReport:
    """事实守恒复核：after_text 的事实必须全部来自「原文 + 用户答案」。

    confirm 在服务端重新执行本检查（不信前端传来的文本）；
    compose 在产出预览时同样执行——发现问题就拒绝输出，而不是先展示再解释。
    """
    allowed = " ".join(
        [original or ""] + [v for v in (answers or {}).values() if v]
    )
    return compare_facts(allowed, after_text or "")


def compose(original: str, answers: dict[str, str]) -> ComposeResult:
    """合成候选描述：原文为事实基底，用户答案按层组织为补充段。

    合成是确定性的（同输入同输出，NFR-08）：不做任何"发挥"，
    只做三件事——剥弱词（用户授权时）、按层拼接、去重。
    """
    base = (original or "").strip()
    clean_answers = {
        layer: (answers or {}).get(layer, "") or "" for layer in LAYER_ORDER
    }
    clean_answers = {k: v.strip() for k, v in clean_answers.items() if v.strip()}

    action = clean_answers.get(LAYER_ACTION, "")
    base_part = _strip_weak_prefix(base) if action else base

    segments: list[dict] = []
    accumulated = ""

    def _add(text: str, source: str) -> None:
        nonlocal accumulated
        normalized = _norm(text)
        if not normalized:
            return
        # 重复判定：答案与已有内容互相包含即视为重复表述，避免合成出车轱辘话
        if accumulated and (normalized in accumulated or accumulated in normalized):
            return
        segments.append({"text": normalized, "source": source})
        accumulated = f"{accumulated}；{normalized}" if accumulated else normalized

    if action:
        _add(action, LAYER_ACTION)
    if base_part:
        _add(base_part, SOURCE_ORIGINAL)
    for layer in (LAYER_QUANT, LAYER_RESULT, LAYER_EVIDENCE):
        if clean_answers.get(layer):
            _add(clean_answers[layer], layer)

    after = "；".join(s["text"] for s in segments) + "。" if segments else ""
    missing = [
        q.layer for q in build_questions(base) if q.needed and not clean_answers.get(q.layer)
    ]

    check = verify_facts(base, clean_answers, after)
    if not check.passed:
        reason = (
            "合成结果包含原文与答案之外的事实，已拒绝输出"
            if check.added
            else "合成结果丢失了原文中的事实，已拒绝输出"
        )
        return ComposeResult(
            status="rejected",
            before=base,
            after="",
            segments=[],
            fact_check=check.to_dict(),
            missing_layers=missing,
            reason=reason,
        )

    return ComposeResult(
        status="composed",
        before=base,
        after=after,
        segments=segments,
        fact_check=check.to_dict(),
        missing_layers=missing,
    )
