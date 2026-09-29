"""FR-06 ATS 适配体检模块（设计文档 4.3，全项目差异化亮点）。

模拟招聘系统的读取过程，逐字段给出四类结论：
  正确读取 correct / 丢失 lost / 错位 misplaced / 编造 fabricated

同时输出 ParseTrace（field / extracted / source_region / rule_applied / verdict），
让"机器是从哪一行、用什么规则读到你的信息的"完全可见——既是产品功能，
也是本模块可被测试断言的依据（设计文档原文：轨迹让判定过程完全可断言）。

与岗位匹配模块共用比对框架（设计文档 4.4）：本模块比对的是"机器读取规则"。
"""
import time

from app.diagnosis.base import DiagnosisContext, DiagnosisModule
from app.diagnosis.models import (
    DIM_MACHINE,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    DiagnosisResult,
    Issue,
    Location,
    build_result,
)
from app.diagnosis import rules

RULE_VERSION = "ats-1.0.0"

# 四类结论（设计文档 4.3 原文命名）
VERDICT_CORRECT = "correct"      # 正确读取
VERDICT_LOST = "lost"            # 丢失
VERDICT_MISPLACED = "misplaced"  # 错位
VERDICT_FABRICATED = "fabricated"  # 编造

VERDICT_LABELS = {
    VERDICT_CORRECT: "正确读取",
    VERDICT_LOST: "丢失",
    VERDICT_MISPLACED: "错位",
    VERDICT_FABRICATED: "编造",
}

# 简历必备区块（缺失即意味着该区块整体读不出来）
REQUIRED_SECTIONS = [
    ("education", "教育背景"),
    ("experience", "实习经历"),
    ("projects", "项目经历"),
    ("skills", "专业技能"),
]


def _is_prefix_truncated(extracted: str, source: str) -> bool:
    """extracted 是否为 source 的前缀截断（展示层截断，不算异常）。

    structurer 的 source_region 是截断展示的原文片段，因此提取值常是它的前缀。
    """
    if not source:
        return False
    head = extracted[:20]
    return source.startswith(head) or head in source


def _looks_misplaced(source: str) -> bool:
    """来源区域含双栏/表格排版痕迹 → 字段被读进错误位置的风险。"""
    return bool(rules.MULTI_COLUMN_HINT_RE.search(source or ""))


class ATSModule(DiagnosisModule):
    """ATS 适配体检（FR-06）。"""

    dimension = DIM_MACHINE
    module_name = "ats_compat"
    rule_version = RULE_VERSION

    def diagnose(self, ctx: DiagnosisContext) -> DiagnosisResult:
        start = time.perf_counter()
        structure = ctx.structure or {}
        trace = ctx.trace or []

        parse_trace = self._build_parse_trace(trace)
        issues: list[Issue] = []

        # 1. 逐字段结论 → 问题项
        for pt in parse_trace:
            issues.extend(self._issues_from_trace(pt))

        # 2. 原文有、结构化结果没有的内容 → 丢失风险
        issues.extend(self._check_unrecognized(ctx))

        # 3. 图标 / 装饰字符 → ATS 读不出
        issues.extend(self._check_symbols(ctx))

        # 4. 区块整体缺失
        issues.extend(self._check_missing_sections(structure))

        elapsed = round((time.perf_counter() - start) * 1000, 1)
        summary = self._summarize(parse_trace)
        return build_result(
            resume_id=ctx.resume_id,
            dimension=self.dimension,
            module_name=self.module_name,
            issues=issues,
            rule_version=self.rule_version,
            elapsed_ms=elapsed,
            reproducible=True,
            meta={"parse_trace": parse_trace, "verdict_summary": summary},
        )

    # ---------- ParseTrace 构建与判定 ----------
    def _build_parse_trace(self, trace: list) -> list[dict]:
        pts: list[dict] = []
        for item in trace:
            field = item.get("field", "")
            extracted = (item.get("extracted") or "").strip()
            source = (item.get("source_region") or "").strip()
            rule = item.get("rule_applied", "")

            # 章节标记与内容字段是两类 trace：
            # section.* 的 extracted 是章节标识符（education），source_region 是原文标题行
            # （教育背景），二者本就不存在子串关系——不能按"内容字段"的规则判定，
            # 否则会把正常识别的标题误报成"编造"。
            if field.startswith("section."):
                verdict, reason = self._judge_section_title(source)
                pts.append(
                    {
                        "field": field,
                        "kind": "section",
                        "extracted": extracted,
                        "source_region": source,
                        "rule_applied": rule,
                        "verdict": verdict,
                        "reason": reason,
                    }
                )
                continue

            if not extracted:
                verdict = VERDICT_LOST
                reason = "未提取到任何内容"
            elif source and not _is_prefix_truncated(extracted, source):
                verdict = VERDICT_FABRICATED
                reason = "提取值在原文对应区域中找不到，疑似相邻字段串行或误抽取"
            elif _looks_misplaced(source):
                verdict = VERDICT_MISPLACED
                reason = "来源区域含制表符/多空格，疑似双栏或表格排版导致字段错位"
            else:
                verdict = VERDICT_CORRECT
                reason = "字段被完整正确提取"

            pts.append(
                {
                    "field": field,
                    "kind": "field",
                    "extracted": extracted,
                    "source_region": source,
                    "rule_applied": rule,
                    "verdict": verdict,
                    "reason": reason,
                }
            )
        return pts

    def _judge_section_title(self, source: str) -> tuple[str, str]:
        """章节标题行的读取判定：能被识别为标准标题即"正确读取"。

        标题含装饰符号/图标时，机器可能读成乱码，归为错位风险。
        """
        if not source:
            return VERDICT_LOST, "章节标题行为空"
        if rules.DECORATION_RE.search(source):
            return VERDICT_MISPLACED, "章节标题含装饰符号，机器读取时可能产生乱码"
        return VERDICT_CORRECT, "章节标题被识别为标准区块名"

    def _issues_from_trace(self, pt: dict) -> list[Issue]:
        verdict = pt["verdict"]
        loc = Location(field=pt["field"], snippet=pt["source_region"] or pt["extracted"])

        if verdict == VERDICT_LOST:
            return [
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="ATS·字段丢失",
                    location=loc,
                    problem=f"字段 {pt['field']} 在机器读取时丢失",
                    suggestion="请确认该内容是否为纯文本；图片、图标、艺术字承载的信息机器读不到",
                    evidence=f"提取规则 {pt['rule_applied']} 未产出内容；{pt['reason']}",
                )
            ]
        if verdict == VERDICT_FABRICATED:
            return [
                Issue(
                    severity=SEVERITY_CRITICAL,
                    category="ATS·内容编造",
                    location=loc,
                    problem=f"字段 {pt['field']} 读出了原文没有的内容「{pt['extracted'][:30]}」",
                    suggestion="检查该区域是否与相邻字段贴得太近，或使用了非标准分隔符",
                    evidence=pt["reason"],
                )
            ]
        if verdict == VERDICT_MISPLACED:
            return [
                Issue(
                    severity=SEVERITY_MAJOR,
                    category="ATS·字段错位",
                    location=loc,
                    problem=f"字段 {pt['field']} 可能被读入了错误位置",
                    suggestion="改用单栏排版，避免用表格/制表符做分栏；用标准小标题分隔区块",
                    evidence=pt["reason"],
                )
            ]
        return []

    # ---------- 未识别内容 → 丢失风险 ----------
    def _check_unrecognized(self, ctx: DiagnosisContext) -> list[Issue]:
        issues: list[Issue] = []
        blocks = ctx.unrecognized or []
        for idx, block in enumerate(blocks):
            text = (block.get("text") or "").strip()
            if len(text) < 4:
                continue
            # 短块（如"个人爱好"）信息量低，降为次要；长段正文读不进去才是真问题
            severity = SEVERITY_MAJOR if len(text) >= 30 else SEVERITY_MINOR
            issues.append(
                Issue(
                    severity=severity,
                    category="ATS·内容丢失",
                    location=Location(field=f"unrecognized[{idx}]", snippet=text[:80]),
                    problem="有一段原文内容无法归入任何字段，机器读取时极可能被丢弃",
                    suggestion="为该段补一个标准小标题（如「专业技能」「荣誉奖项」），让它可被归类",
                    evidence=f"未识别原因：{block.get('reason', '无法归入已知字段')}",
                )
            )
        return issues

    # ---------- 图标 / 装饰字符 ----------
    def _check_symbols(self, ctx: DiagnosisContext) -> list[Issue]:
        issues: list[Issue] = []
        for idx, block in enumerate(ctx.unrecognized or []):
            text = block.get("text") or ""
            if rules.ICON_RE.search(text):
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="ATS·图标信息",
                        location=Location(field=f"unrecognized[{idx}]", snippet=text[:60]),
                        problem="使用了图标/emoji 承载信息",
                        suggestion="把图标换成文字标签（如用「电话」而不是电话图标）",
                        evidence="检测到图标类字符，ATS 通常无法解析其语义",
                    )
                )
                break
        for idx, block in enumerate(ctx.unrecognized or []):
            text = block.get("text") or ""
            if rules.DECORATION_RE.search(text):
                issues.append(
                    Issue(
                        severity=SEVERITY_MINOR,
                        category="ATS·装饰字符",
                        location=Location(field=f"unrecognized[{idx}]", snippet=text[:60]),
                        problem="标题中使用了特殊装饰符号",
                        suggestion="装饰符号请删除或替换为普通文字，避免机器读取时产生乱码",
                        evidence="检测到 ★◆● 等装饰字符",
                    )
                )
                break
        return issues

    # ---------- 区块缺失 ----------
    def _check_missing_sections(self, structure: dict) -> list[Issue]:
        issues: list[Issue] = []
        for key, label in REQUIRED_SECTIONS:
            if not (structure.get(key) or []):
                issues.append(
                    Issue(
                        severity=SEVERITY_MAJOR,
                        category="ATS·区块缺失",
                        location=Location(field=key, snippet=""),
                        problem=f"未识别到「{label}」区块",
                        suggestion=f"如确有{label}内容，请使用标准小标题「{label}」单独成段",
                        evidence=f"结构化结果 {key} 为空",
                    )
                )
        return issues

    def _summarize(self, parse_trace: list[dict]) -> dict:
        summary = {VERDICT_CORRECT: 0, VERDICT_LOST: 0, VERDICT_MISPLACED: 0, VERDICT_FABRICATED: 0}
        for pt in parse_trace:
            summary[pt["verdict"]] = summary.get(pt["verdict"], 0) + 1
        return summary


MODULE = ATSModule()
