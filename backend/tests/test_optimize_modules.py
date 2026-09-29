"""优化模块单元测试（设计文档 4.5.7 可测试性四点措施 + 7.3 负面测试要点）。

对应设计文档的四条可测试性措施：
  1. 事实清单结构化输出 → 把"是否编造"变成集合比对，可直接断言 violated/added 为空
  2. 改动点结构化输出   → "改得对不对"变成可分类统计的对象
  3. 风险等级带判定依据 → 可断言"误判为可自动应用的用例数为 0"
  4. 全量快照版本机制   → 撤销"逐字一致"结构性成立（见接口测试）
"""
import pytest

from app.optimize.changes import (
    CLASS_FORMAT,
    CLASS_PUNCTUATION,
    CLASS_STRUCTURE,
    CLASS_TYPO,
    CLASS_WORDING,
    SAFE_CLASSES,
    ChangePoint,
    compute_change_points,
    normalize_for_fingerprint,
    semantic_fingerprint,
    unsafe_change_rate,
)
from app.optimize.engine import (
    STATUS_GENERATED,
    STATUS_REJECTED,
    STATUS_SUGGESTION_ONLY,
    AIStubEngine,
    RewriteRequest,
    RuleRewriteEngine,
    fix_date_format,
    fix_mixed_punctuation,
    fix_typos,
)
from app.optimize.facts import compare_facts, extract_facts
from app.optimize.risk import RISK_AUTO_SAFE, RISK_NEEDS_REVIEW, grade_risk


# ============ 事实抽取与守恒（措施 1） ============

class TestFactConservation:
    def test_identical_text_passes(self):
        report = compare_facts("浙江大学 本科 2020.09-2024.06", "浙江大学 本科 2020.09-2024.06")
        assert report.passed
        assert report.facts_before

    def test_same_fact_different_writing_passes(self):
        """同一事实的不同写法必须守恒，否则格式统一会被误判为编造。"""
        report = compare_facts(
            "2020.09-2024.06 在浙江大学", "2020年9月-2024年6月 在浙江大学"
        )
        assert report.passed
        assert report.violated == []
        assert report.added == []

    def test_changed_number_is_violation(self):
        """数字被放大是典型编造，必须被抓到。"""
        report = compare_facts("日均支撑 10 万次调用", "日均支撑 500 万次调用")
        assert not report.passed
        assert any(f["kind"] == "number" for f in report.violated)
        assert any(f["kind"] == "number" for f in report.added)

    def test_changed_school_is_violation(self):
        report = compare_facts("浙江大学 本科", "北京大学 本科")
        assert not report.passed
        assert any(f["kind"] == "school" for f in report.violated)

    def test_changed_degree_is_violation(self):
        report = compare_facts("本科毕业", "硕士毕业")
        assert not report.passed
        assert any(f["kind"] == "degree" for f in report.violated)

    def test_added_fact_is_violation(self):
        """新增原文没有的事实同样判失败（added 非空即失败）。"""
        report = compare_facts("负责接口开发", "负责接口开发，管理 5 人团队")
        assert not report.passed
        assert report.added

    def test_tech_term_extracted(self):
        facts = extract_facts("使用 Python 与 MySQL 完成开发")
        values = {f.value for f in facts.facts}
        assert "python" in values
        assert "mysql" in values

    def test_year_not_counted_as_standalone_number(self):
        """时间段内的年份不应被当成独立数字事实（否则改日期会误报 violated）。"""
        facts = extract_facts("2023.06-2023.12 实习")
        assert not any(f.kind == "number" and f.value == "2023" for f in facts.facts)

    def test_school_name_not_polluted_by_prefix(self):
        facts = extract_facts("2024年6月 在浙江大学")
        schools = [f.value for f in facts.facts if f.kind == "school"]
        assert "浙江大学" in schools


# ============ 改动点与语义指纹（措施 2） ============

class TestChangePoints:
    def test_no_change_no_points(self):
        assert compute_change_points("abc", "abc") == []

    def test_punctuation_change_classified(self):
        points = compute_change_points("开发, 使用", "开发，使用")
        assert points and points[0].change_class == CLASS_PUNCTUATION

    def test_typo_change_classified(self):
        """错别字必须是 typo 而非 wording——否则会被判成需人工确认。"""
        points = compute_change_points("并既使上线", "并即使上线")
        assert points
        assert all(p.change_class == CLASS_TYPO for p in points)

    def test_date_format_change_classified(self):
        points = compute_change_points("2023年6月-2023年12月", "2023.06-2023.12")
        assert points
        assert all(p.change_class == CLASS_FORMAT for p in points)

    def test_wording_change_classified(self):
        points = compute_change_points("负责 3 个模块", "主导 3 个核心模块的架构设计")
        assert points
        assert any(p.change_class == CLASS_WORDING for p in points)

    def test_reorder_classified(self):
        points = compute_change_points("Python 与 Java", "Java 与 Python")
        assert points
        assert any(p.change_class == CLASS_STRUCTURE for p in points)

    def test_spans_are_accurate(self):
        before = "abcdef"
        after = "abcXef"
        points = compute_change_points(before, after)
        assert len(points) == 1
        assert before[slice(*points[0].before_span)] == "d"
        assert after[slice(*points[0].after_span)] == "X"

    def test_unsafe_change_rate_zero_for_safe_rewrite(self):
        points = compute_change_points("开发, 使用", "开发，使用")
        assert unsafe_change_rate(points) == 0.0

    def test_semantic_fingerprint_insensitive_to_safe_variants(self):
        assert semantic_fingerprint("2020.09-2024.06") == semantic_fingerprint("2020年9月-2024年6月")
        assert semantic_fingerprint("使用 Python") == semantic_fingerprint("使用Python")
        assert semantic_fingerprint("并既使上线") == semantic_fingerprint("并即使上线")

    def test_semantic_fingerprint_sensitive_to_meaning(self):
        assert semantic_fingerprint("负责开发") != semantic_fingerprint("主导设计")

    def test_normalize_keeps_digits(self):
        assert normalize_for_fingerprint("10 万次").strip() != ""


# ============ 风险分级（措施 3：误判数必须为 0） ============

class TestRiskGrading:
    def _grade(self, before: str, after: str):
        points = compute_change_points(before, after)
        return grade_risk(before, after, points)

    def test_punctuation_only_is_auto_safe(self):
        g = self._grade("开发, 使用", "开发，使用")
        assert g.risk_level == RISK_AUTO_SAFE

    def test_typo_only_is_auto_safe(self):
        g = self._grade("并既使上线", "并即使上线")
        assert g.risk_level == RISK_AUTO_SAFE

    def test_date_format_only_is_auto_safe(self):
        g = self._grade("2023年6月-2023年12月", "2023.06-2023.12")
        assert g.risk_level == RISK_AUTO_SAFE

    def test_wording_change_is_needs_review(self):
        g = self._grade("负责 3 个模块", "主导 3 个核心模块的架构设计")
        assert g.risk_level == RISK_NEEDS_REVIEW

    def test_exaggeration_is_needs_review(self):
        """"负责"→"主导"只改两个字却可能构成夸大，必须拦下。"""
        g = self._grade("负责订单服务", "主导订单服务体系")
        assert g.risk_level == RISK_NEEDS_REVIEW

    def test_structure_change_is_needs_review(self):
        g = self._grade("Python 与 Java", "Java 与 Python")
        assert g.risk_level == RISK_NEEDS_REVIEW

    def test_no_change_is_needs_review(self):
        """无改动时保守判为需确认，不自动应用空操作。"""
        g = self._grade("原样文本", "原样文本")
        assert g.risk_level == RISK_NEEDS_REVIEW

    def test_grade_carries_reasons(self):
        """措施 3：判定可查——risk_level 必须附带判定依据。"""
        g = self._grade("开发, 使用", "开发，使用")
        assert g.reasons
        assert g.fingerprint_before and g.fingerprint_after

    def test_never_misclassifies_semantic_change_as_auto_safe(self):
        """核心断言：任何改变语义的改写都不得被判为 auto_safe（误判数必须为 0）。"""
        semantic_changes = [
            ("负责 3 个模块", "主导 3 个核心模块的架构设计"),
            ("参与开发", "独立负责整体开发"),
            ("日均 10 万次", "日均 500 万次"),
            ("Python 与 Java", "Java 与 Python"),
            ("完成测试", "建立完整的自动化测试体系"),
        ]
        for before, after in semantic_changes:
            g = self._grade(before, after)
            assert g.risk_level == RISK_NEEDS_REVIEW, f"被误判为可自动应用：{before!r} → {after!r}"

    def test_all_safe_classes_are_in_whitelist(self):
        assert SAFE_CLASSES == {CLASS_PUNCTUATION, CLASS_TYPO, CLASS_FORMAT}


# ============ 确定性修正函数 ============

class TestDeterministicFixers:
    def test_fix_mixed_punctuation_removes_trailing_space(self):
        assert fix_mixed_punctuation("开发, 使用") == "开发，使用"

    def test_fix_mixed_punctuation_keeps_legitimate_english(self):
        """CI/CD、GPA 3.6/4.0 这类合法英文标点不能被改坏。"""
        text = "熟悉 CI/CD 与 Git 协作，GPA 3.6/4.0"
        assert fix_mixed_punctuation(text) == text

    def test_fix_typos(self):
        assert fix_typos("并既使上线") == "并即使上线"

    def test_fix_date_format_dot(self):
        assert fix_date_format("2021年9月-2025年6月", "dot") == "2021.09-2025.06"

    def test_fix_date_format_cn(self):
        assert fix_date_format("2021.09-2025.06", "cn") == "2021年9月-2025年6月"


# ============ 改写引擎（五步链路） ============

class TestRuleRewriteEngine:
    def setup_method(self):
        self.engine = RuleRewriteEngine()

    def _req(self, category: str, text: str) -> RewriteRequest:
        return RewriteRequest(
            issue={"issue_id": "iss-test", "category": category},
            field_name="experience[0].description",
            field_text=text,
        )

    def test_punctuation_issue_produces_auto_safe_rewrite(self):
        outcome = self.engine.rewrite(self._req("中英文标点混用", "负责开发, 使用 Python"))
        assert outcome.status == STATUS_GENERATED
        assert outcome.risk_level == RISK_AUTO_SAFE
        assert outcome.after == "负责开发，使用 Python"

    def test_typo_issue_produces_auto_safe_rewrite(self):
        outcome = self.engine.rewrite(self._req("错别字", "负责开发并既使上线"))
        assert outcome.status == STATUS_GENERATED
        assert outcome.risk_level == RISK_AUTO_SAFE
        assert "即使" in outcome.after

    def test_fact_check_attached_to_generated_rewrite(self):
        outcome = self.engine.rewrite(self._req("中英文标点混用", "负责开发, 使用 Python 与 MySQL"))
        assert outcome.fact_check is not None
        assert outcome.fact_check.passed

    def test_engine_refuses_to_write_content_for_user(self):
        """要素缺失/空话套话必须降级为仅建议——规则引擎不替用户编造经历。"""
        for category in ("要素缺失·结果如何", "空话套话", "缺少量化结果", "岗位匹配·技能缺失"):
            outcome = self.engine.rewrite(self._req(category, "吃苦耐劳，有团队精神"))
            assert outcome.status == STATUS_SUGGESTION_ONLY
            assert outcome.after == ""

    def test_no_op_rewrite_is_suggestion_only(self):
        outcome = self.engine.rewrite(self._req("中英文标点混用", "本来就没有英文标点"))
        assert outcome.status == STATUS_SUGGESTION_ONLY


class TestAIStubEngine:
    """AI 桩：验证降级路径与事实守恒校验真的生效（设计文档 7.3 最重要的负面测试）。"""

    def test_fabricating_stub_is_rejected(self):
        engine = AIStubEngine(fabricate=True)
        outcome = engine.rewrite(
            RewriteRequest(
                issue={"issue_id": "i", "category": "表达力度弱"},
                field_name="experience[0].description",
                field_text="日均支撑 10 万次调用",
            )
        )
        assert outcome.status == STATUS_REJECTED
        # 关键：违规内容必须不出现在改写结果里
        assert outcome.after == ""
        assert "500" not in outcome.after

    def test_rejection_reason_names_the_violation(self):
        engine = AIStubEngine(fabricate=True)
        outcome = engine.rewrite(
            RewriteRequest(
                issue={"issue_id": "i", "category": "x"},
                field_name="f",
                field_text="日均支撑 10 万次调用",
            )
        )
        assert "事实" in outcome.reason
        assert outcome.fact_check is not None
        assert not outcome.fact_check.passed

    def test_well_behaved_stub_generates(self):
        engine = AIStubEngine(fabricate=False)
        outcome = engine.rewrite(
            RewriteRequest(
                issue={"issue_id": "i", "category": "中英文标点混用"},
                field_name="f",
                field_text="负责开发, 使用 Python",
            )
        )
        assert outcome.status == STATUS_GENERATED
        assert outcome.risk_level == RISK_AUTO_SAFE

    def test_fabricating_stub_adding_content_is_rejected(self):
        """无数字可放大时，桩会追加无依据内容——同样必须被拒。"""
        engine = AIStubEngine(fabricate=True)
        outcome = engine.rewrite(
            RewriteRequest(
                issue={"issue_id": "i", "category": "x"},
                field_name="f",
                field_text="负责接口开发与日常维护",
            )
        )
        assert outcome.status == STATUS_REJECTED
        assert outcome.fact_check.added


# ============ 草稿字段与未识别内容（FR-03：进得了草稿，出得了导出） ============

class TestDraftFieldsUnrecognized:
    """未识别内容必须有正式落点。

    修复的缺陷：诊断会针对未识别内容报问题项（location.field=unrecognized[0]），
    但草稿字段列表里没有这些内容 → 用户点"改写"直接撞 6001 死胡同，
    既改不了也删不掉；同时导出时这些内容会被静默丢弃。
    """

    STRUCTURE = {
        "basic_info": {"name": "张伟", "phone": "025-12345678", "email": "z@e.com", "city": "南京"},
        "education": [{"school": "南京大学", "major": "计算机", "degree": "本科", "period": "2021.09-2025.06", "description": None}],
        "experience": [],
        "projects": [],
        "skills": ["Python"],
        "honors": [],
    }
    UNRECOGNIZED = [
        {"text": "个人爱好：阅读、跑步、摄影", "reason": "无法归入已知字段"},
        {"text": "自我评价：本人性格开朗", "reason": "无法归入已知字段"},
    ]

    def test_unrecognized_becomes_editable_fields(self):
        from app.optimize.draft_fields import structure_to_fields

        fields = structure_to_fields(self.STRUCTURE, self.UNRECOGNIZED)
        names = [f["field_name"] for f in fields]
        assert "unrecognized[0]" in names
        assert "unrecognized[1]" in names
        got = next(f for f in fields if f["field_name"] == "unrecognized[0]")
        assert got["value"] == "个人爱好：阅读、跑步、摄影"
        # source 单独标记，前端据此提示"机器读不了，需人工处理"
        assert got["source"] == "unrecognized"

    def test_unrecognized_survives_structure_round_trip(self):
        from app.optimize.draft_fields import fields_to_structure, structure_to_fields

        fields = structure_to_fields(self.STRUCTURE, self.UNRECOGNIZED)
        back = fields_to_structure(fields)
        assert [u["text"] for u in back["unrecognized"]] == [
            "个人爱好：阅读、跑步、摄影",
            "自我评价：本人性格开朗",
        ]

    def test_unrecognized_exported_not_silently_dropped(self):
        from app.optimize.draft_fields import fields_to_lines, structure_to_fields

        fields = structure_to_fields(self.STRUCTURE, self.UNRECOGNIZED)
        lines = fields_to_lines(fields)
        joined = "\n".join(lines)
        assert "个人爱好：阅读、跑步、摄影" in joined
        assert "自我评价：本人性格开朗" in joined

    def test_exported_unrecognized_stays_unrecognized_after_reparse(self):
        """复检闭环：导出文本重新解析后，未识别内容必须仍未识别。

        若不用「未归类内容」标题包裹，这些行会被吸进上一个章节（荣誉/经历），
        ATS 对比结论就会因为"机器突然读到了"而虚假变好。
        """
        from app.optimize.draft_fields import fields_to_lines, structure_to_fields
        from app.parser.structurer import structure_document

        fields = structure_to_fields(self.STRUCTURE, self.UNRECOGNIZED)
        parsed = structure_document(fields_to_lines(fields), "rule-test")
        texts = [u["text"] for u in parsed.unrecognized]
        assert "个人爱好：阅读、跑步、摄影" in texts
        assert "自我评价：本人性格开朗" in texts
        # 且不能被改判成荣誉或经历
        assert not parsed.structure["honors"]
        assert not parsed.structure["experience"]

    def test_empty_unrecognized_adds_no_fields(self):
        from app.optimize.draft_fields import structure_to_fields

        assert structure_to_fields(self.STRUCTURE, []) == structure_to_fields(self.STRUCTURE)
        assert structure_to_fields(self.STRUCTURE) == structure_to_fields(self.STRUCTURE, None)

    def test_blank_unrecognized_text_skipped(self):
        from app.optimize.draft_fields import structure_to_fields

        fields = structure_to_fields(self.STRUCTURE, [{"text": "   ", "reason": "x"}])
        assert not [f for f in fields if f["field_name"].startswith("unrecognized[")]


class TestOtherSectionKeyword:
    """用户简历里显式的「其他信息」区块：原样进未识别池，不塞进上一个章节。"""

    def test_other_section_goes_to_unrecognized(self):
        from app.parser.structurer import structure_document

        text = """张三
电话：0464-4778320
邮箱：zhang@example.com

荣誉奖项
校级三等奖学金

其他信息
个人爱好：阅读与长跑
"""
        parsed = structure_document(text.split("\n"), "rule-test")
        assert parsed.structure["honors"] == ["校级三等奖学金"]
        texts = [u["text"] for u in parsed.unrecognized]
        assert "个人爱好：阅读与长跑" in texts

    def test_other_project_title_still_parsed_as_projects(self):
        """防回归：关键词刻意不用裸「其他」——「其他项目」必须仍归到项目经历。"""
        from app.parser.structurer import structure_document

        text = """李四
电话：0451-7361558
邮箱：li@example.com

其他项目
2023.03-2023.09 内部运维平台 后端开发
负责告警模块开发
"""
        parsed = structure_document(text.split("\n"), "rule-test")
        assert len(parsed.structure["projects"]) == 1
        assert parsed.structure["projects"][0]["name"] == "内部运维平台"
