"""改写风险分级器（O-06 / O-07 的分界线，设计文档 4.5.4）。

分级依据是**改动是否改变语义**，而不是改动的大小：
  改一个标点只动 1 个字符，但完全不改变语义 → auto_safe
  把"负责 3 个模块"改成"主导 3 个核心模块"只改 4 个字，却可能构成夸大 → needs_review
**以字符量分级会同时放过后者、拦下前者，两个方向都错。**

三条硬约束（对应测试用例）：
  1. 保守优先：无法判断时一律 needs_review。误把语义改写判为可自动应用是**严重缺陷**，反之只是体验损失。
  2. 不可绕过：批量应用只能筛选 auto_safe，且**判定只能在服务端做**。
  3. 判定可查：risk_level 必须附带判定依据。
"""
from dataclasses import dataclass, field

from app.optimize.changes import (
    CLASS_LABELS,
    SAFE_CLASSES,
    ChangePoint,
    semantic_fingerprint,
)

RISK_AUTO_SAFE = "auto_safe"
RISK_NEEDS_REVIEW = "needs_review"

RISK_LABELS = {
    RISK_AUTO_SAFE: "可自动应用",
    RISK_NEEDS_REVIEW: "需人工确认",
}


@dataclass
class RiskGrade:
    risk_level: str
    reasons: list[str] = field(default_factory=list)
    fingerprint_before: str = ""
    fingerprint_after: str = ""
    fingerprint_match: bool = False
    safe_classes: list[str] = field(default_factory=list)
    unsafe_classes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "risk_label": RISK_LABELS.get(self.risk_level, self.risk_level),
            "reasons": self.reasons,
            "fingerprint_before": self.fingerprint_before,
            "fingerprint_after": self.fingerprint_after,
            "fingerprint_match": self.fingerprint_match,
            "safe_classes": self.safe_classes,
            "unsafe_classes": self.unsafe_classes,
        }


def grade_risk(before: str, after: str, change_points: list[ChangePoint]) -> RiskGrade:
    """判定改写的风险等级。

    auto_safe 需同时满足两个条件：
      ① 所有改动点的 change_class 都属于"不改变语义"的白名单；
      ② 改写前后的语义指纹一致（双保险，任一条不满足即降级）。
    """
    fp_before = semantic_fingerprint(before)
    fp_after = semantic_fingerprint(after)
    fingerprint_match = fp_before == fp_after

    safe = sorted({c.change_class for c in change_points if c.change_class in SAFE_CLASSES})
    unsafe = sorted({c.change_class for c in change_points if c.change_class not in SAFE_CLASSES})

    reasons: list[str] = []
    if not change_points:
        reasons.append("无改动点")
    else:
        reasons.append(
            "改动类别：" + "、".join(CLASS_LABELS.get(c.change_class, c.change_class) for c in change_points)
        )

    if unsafe:
        # 命中任何可能影响语义的类别 → 必须人工确认
        labels = "、".join(CLASS_LABELS.get(c, c) for c in unsafe)
        reasons.append(f"含可能改变语义的改动类别：{labels}")
        reasons.append("依据设计文档 4.5.4：措辞/结构类改动必须逐条人工确认")
        return RiskGrade(
            risk_level=RISK_NEEDS_REVIEW,
            reasons=reasons,
            fingerprint_before=fp_before,
            fingerprint_after=fp_after,
            fingerprint_match=fingerprint_match,
            safe_classes=safe,
            unsafe_classes=unsafe,
        )

    if not fingerprint_match:
        # 类别看似安全但语义指纹不一致 → 保守降级（无法判断时一律 needs_review）
        reasons.append("改动类别虽属规范类，但语义指纹不一致，按保守原则降级")
        return RiskGrade(
            risk_level=RISK_NEEDS_REVIEW,
            reasons=reasons,
            fingerprint_before=fp_before,
            fingerprint_after=fp_after,
            fingerprint_match=fingerprint_match,
            safe_classes=safe,
            unsafe_classes=unsafe,
        )

    if not change_points:
        reasons.append("无实际改动，按保守原则不自动应用")
        return RiskGrade(
            risk_level=RISK_NEEDS_REVIEW,
            reasons=reasons,
            fingerprint_before=fp_before,
            fingerprint_after=fp_after,
            fingerprint_match=fingerprint_match,
            safe_classes=safe,
            unsafe_classes=unsafe,
        )

    reasons.append(f"语义指纹一致，且改动仅涉及 {'、'.join(CLASS_LABELS.get(c, c) for c in safe)}")
    return RiskGrade(
        risk_level=RISK_AUTO_SAFE,
        reasons=reasons,
        fingerprint_before=fp_before,
        fingerprint_after=fp_after,
        fingerprint_match=fingerprint_match,
        safe_classes=safe,
        unsafe_classes=unsafe,
    )
