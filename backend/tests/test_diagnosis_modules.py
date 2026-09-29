"""诊断模块单元测试（设计文档 8.2 单元测试策略）。

每个诊断模块以「固定结构化输入 → 期望诊断结果」的方式独立测试，
**不需要启动服务、不需要数据库**——这是 NFR-07（模块解耦）的验证方式。

同时覆盖 NFR-08（可复现）：相同输入两次执行，结果 ID 与结论必须一致。
"""
import pytest

from app.diagnosis.base import DiagnosisContext
from app.diagnosis.content import MODULE as content_module
from app.diagnosis.machine import (
    VERDICT_CORRECT,
    VERDICT_FABRICATED,
    VERDICT_MISPLACED,
    MODULE as machine_module,
)
from app.diagnosis.match import (
    MODULE as match_module,
    contains_term,
    extract_jd_keys,
)
from app.diagnosis.models import (
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    SEVERITY_MINOR,
    Issue,
    Location,
    build_result,
    compute_score,
)
from app.diagnosis.norm import MODULE as norm_module
from app.diagnosis.runner import (
    DIM_CONTENT,
    DIM_MACHINE,
    DIM_MATCH,
    DIM_NORM,
    DIM_STRUCTURE,
    build_report,
    health_score,
    run_diagnosis,
    sort_issues,
)


def _ctx(structure=None, trace=None, unrecognized=None, jd=None) -> DiagnosisContext:
    return DiagnosisContext(
        resume_id="r-test",
        structure=structure or {},
        trace=trace or [],
        unrecognized=unrecognized or [],
        jd=jd,
    )


def _categories(result) -> set[str]:
    return {i.category for i in result.issues}


def _clean_structure() -> dict:
    """一份没有明显问题的简历结构，用于"干净输入 → 无问题"断言。"""
    return {
        "basic_info": {
            "name": "张三",
            "phone": "13812345678",
            "email": "zhangsan@example.com",
            "city": "杭州",
        },
        "education": [
            {
                "school": "浙江大学",
                "major": "计算机科学与技术",
                "degree": "本科",
                "period": "2020.09-2024.06",
            }
        ],
        "experience": [
            {
                "company": "字节跳动科技有限公司",
                "role": "后端开发实习生",
                "period": "2023.06-2023.12",
                "description": "设计并开发订单服务接口，基于 Python 与 MySQL，"
                "日均支撑 10 万次调用，接口错误率降至 0.3%",
            }
        ],
        "projects": [
            {
                "name": "分布式秒杀系统",
                "role": "核心开发",
                "period": "2023.03-2023.05",
                "description": "设计库存扣减方案并使用 Redis 缓存热点数据，"
                "QPS 从 800 提升到 3000，平均耗时下降 60%",
            }
        ],
        "skills": ["Python", "Java", "MySQL", "Redis", "Docker", "Linux"],
        "honors": ["校级优秀学生奖学金"],
    }


# ============ 统一诊断结果模型 ============

class TestDiagnosisModel:
    def test_issue_id_is_deterministic(self):
        """相同输入 → 相同 issue_id（NFR-08）。"""
        def make():
            return Issue(
                severity=SEVERITY_MINOR,
                category="中英文标点混用",
                location=Location(field="a", snippet="x"),
                problem="p",
                suggestion="s",
                evidence="e",
            )

        assert make().issue_id == make().issue_id

    def test_issue_id_differs_by_content(self):
        a = Issue(SEVERITY_MINOR, "cat", Location("f1", "s"), "p1", "s", "e")
        b = Issue(SEVERITY_MINOR, "cat", Location("f1", "s"), "p2", "s", "e")
        assert a.issue_id != b.issue_id

    def test_compute_score_penalties(self):
        issues = [
            Issue(SEVERITY_CRITICAL, "c", Location("f"), "p", "s", "e"),
            Issue(SEVERITY_MAJOR, "c", Location("f"), "p", "s", "e"),
            Issue(SEVERITY_MINOR, "c", Location("f"), "p", "s", "e"),
        ]
        assert compute_score(issues) == 100 - 15 - 8 - 3

    def test_compute_score_floor_is_zero(self):
        issues = [Issue(SEVERITY_CRITICAL, "c", Location("f"), "p", "s", "e") for _ in range(10)]
        assert compute_score(issues) == 0

    def test_score_clamped_to_0_100(self):
        result = build_result("r", DIM_NORM, "m", [], "v-1")
        assert 0 <= result.score <= 100

    def test_result_dict_has_meta_contract(self):
        result = build_result("r", DIM_NORM, "m", [], "v-1", elapsed_ms=1.2)
        d = result.to_dict()
        assert d["meta"]["rule_version"] == "v-1"
        assert d["meta"]["elapsed_ms"] == 1.2
        assert d["meta"]["reproducible"] is True


# ============ FR-04 基础规范体检 ============

class TestNormModule:
    def test_clean_resume_has_no_issue(self):
        result = norm_module.diagnose(_ctx(_clean_structure()))
        assert result.issues == []
        assert result.score == 100

    def test_missing_contact_is_critical(self):
        structure = _clean_structure()
        structure["basic_info"]["phone"] = None
        structure["basic_info"]["email"] = None
        result = norm_module.diagnose(_ctx(structure))
        assert "联系方式缺失" in _categories(result)
        critical = [i for i in result.issues if i.severity == SEVERITY_CRITICAL]
        assert critical and critical[0].category == "联系方式缺失"

    def test_invalid_mobile_prefix_is_major(self):
        structure = _clean_structure()
        structure["basic_info"]["phone"] = "10123456789"
        result = norm_module.diagnose(_ctx(structure))
        cats = _categories(result)
        assert "联系方式错误" in cats

    def test_malformed_email_is_major(self):
        structure = _clean_structure()
        structure["basic_info"]["email"] = "zhangsan@example"
        result = norm_module.diagnose(_ctx(structure))
        assert "联系方式错误" in _categories(result)

    def test_irrelevant_personal_info_detected(self):
        structure = _clean_structure()
        structure["basic_info"]["extra"] = {"性别": "男", "年龄": "22"}
        structure["skills"] = ["性别：男", "年龄：22 岁", "Python"]
        result = norm_module.diagnose(_ctx(structure))
        assert "无关个人信息" in _categories(result)

    def test_mixed_punctuation_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "负责订单服务接口开发, 使用 Python 与 MySQL。"
        result = norm_module.diagnose(_ctx(structure))
        assert "中英文标点混用" in _categories(result)

    def test_inconsistent_date_formats_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["period"] = "2023年6月-2023年12月"
        result = norm_module.diagnose(_ctx(structure))
        assert "日期格式不一致" in _categories(result)

    def test_timeline_reversed_detected(self):
        structure = _clean_structure()
        structure["experience"].append(
            {
                "company": "某公司",
                "role": "实习生",
                "period": "2024.06-2024.12",
                "description": "参与后端服务开发与接口联调，日均处理请求 5 万次",
            }
        )
        result = norm_module.diagnose(_ctx(structure))
        assert "时间线倒序" in _categories(result)

    def test_timeline_gap_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["period"] = "2020.06-2020.12"
        structure["experience"].append(
            {
                "company": "某公司",
                "role": "实习生",
                "period": "2023.06-2023.12",
                "description": "参与后端服务开发与接口联调，日均处理请求 5 万次",
            }
        )
        result = norm_module.diagnose(_ctx(structure))
        assert "时间断层" in _categories(result)

    def test_typo_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "负责接口开发并既使上线，使用 Python 完成部署"
        result = norm_module.diagnose(_ctx(structure))
        assert "错别字" in _categories(result)

    def test_reproducible_same_input_same_output(self):
        structure = _clean_structure()
        structure["basic_info"]["phone"] = None
        a = norm_module.diagnose(_ctx(structure))
        b = norm_module.diagnose(_ctx(structure))
        assert [i.issue_id for i in a.issues] == [i.issue_id for i in b.issues]
        assert a.score == b.score
        assert a.reproducible is True


# ============ FR-05 内容质量诊断 ============

class TestContentModule:
    def test_clean_description_has_no_issue(self):
        result = content_module.diagnose(_ctx(_clean_structure()))
        assert result.issues == []
        assert result.score == 100

    def test_missing_result_element_is_major(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "负责订单服务接口开发与日常维护"
        result = content_module.diagnose(_ctx(structure))
        assert "要素缺失·结果如何" in _categories(result)

    def test_missing_method_element(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "负责订单服务接口开发，日均支撑 10 万次调用"
        result = content_module.diagnose(_ctx(structure))
        assert "要素缺失·怎么做" in _categories(result)

    def test_cliche_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "工作认真负责，吃苦耐劳，抗压能力强，有团队精神"
        result = content_module.diagnose(_ctx(structure))
        assert "空话套话" in _categories(result)

    def test_weak_expression_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "参与了订单服务开发，协助完成了接口测试工作"
        result = content_module.diagnose(_ctx(structure))
        assert "表达力度弱" in _categories(result)

    def test_no_quantification_detected(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "负责订单服务接口的设计与开发，基于 Python 实现"
        result = content_module.diagnose(_ctx(structure))
        assert "缺少量化结果" in _categories(result)

    def test_empty_description_is_major(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = ""
        result = content_module.diagnose(_ctx(structure))
        assert "描述缺失" in _categories(result)

    def test_missing_skills_is_major(self):
        structure = _clean_structure()
        structure["skills"] = []
        result = content_module.diagnose(_ctx(structure))
        assert "技能缺失" in _categories(result)

    def test_every_issue_carries_evidence_and_location(self):
        """原则三：每条结论必须带定位与依据，否则测试无法验证判定过程。"""
        structure = _clean_structure()
        structure["experience"][0]["description"] = "吃苦耐劳，有团队精神"
        result = content_module.diagnose(_ctx(structure))
        assert result.issues
        for issue in result.issues:
            assert issue.location.field
            assert issue.evidence
            assert issue.suggestion


# ============ FR-06 ATS 适配体检 ============

class TestMachineModule:
    def test_correct_field_verdict(self):
        trace = [
            {
                "field": "basic_info.email",
                "extracted": "a@b.com",
                "source_region": "邮箱：a@b.com",
                "rule_applied": "regex:email",
            }
        ]
        result = machine_module.diagnose(_ctx(_clean_structure(), trace=trace))
        pts = {p["field"]: p for p in result.meta["parse_trace"]}
        assert pts["basic_info.email"]["verdict"] == VERDICT_CORRECT
        assert result.meta["verdict_summary"][VERDICT_CORRECT] >= 1

    def test_section_title_is_not_reported_as_fabricated(self):
        """回归用例：section.* 的 extracted 是章节标识符，与原文标题行不构成子串关系，
        曾因按"内容字段"规则判定而被误报为"编造"，导致健康分被严重拉低。"""
        trace = [
            {
                "field": "section.education",
                "extracted": "education",
                "source_region": "教育背景",
                "rule_applied": "keyword:教育背景",
            }
        ]
        result = machine_module.diagnose(_ctx(_clean_structure(), trace=trace))
        pts = {p["field"]: p for p in result.meta["parse_trace"]}
        assert pts["section.education"]["verdict"] == VERDICT_CORRECT
        assert "ATS·内容编造" not in _categories(result)

    def test_extracted_absent_from_source_is_fabricated(self):
        trace = [
            {
                "field": "basic_info.name",
                "extracted": "李四",
                "source_region": "王五 电话：13812345678",
                "rule_applied": "heuristic:short_cn_line",
            }
        ]
        result = machine_module.diagnose(_ctx(_clean_structure(), trace=trace))
        pts = {p["field"]: p for p in result.meta["parse_trace"]}
        assert pts["basic_info.name"]["verdict"] == VERDICT_FABRICATED
        fabricated = [i for i in result.issues if i.category == "ATS·内容编造"]
        assert fabricated and fabricated[0].severity == SEVERITY_CRITICAL

    def test_multi_column_source_is_misplaced(self):
        trace = [
            {
                "field": "experience[0].company",
                "extracted": "某公司",
                "source_region": "某公司    实习生    2023.06-2023.12",
                "rule_applied": "regex:company",
            }
        ]
        result = machine_module.diagnose(_ctx(_clean_structure(), trace=trace))
        pts = {p["field"]: p for p in result.meta["parse_trace"]}
        assert pts["experience[0].company"]["verdict"] == VERDICT_MISPLACED

    def test_unrecognized_content_reported_as_loss(self):
        blocks = [
            {"text": "个人爱好广泛，喜欢阅读与跑步，保持每周三次运动习惯。", "reason": "无法归入已知字段"}
        ]
        result = machine_module.diagnose(_ctx(_clean_structure(), unrecognized=blocks))
        assert "ATS·内容丢失" in _categories(result)

    def test_missing_section_reported(self):
        structure = _clean_structure()
        structure["projects"] = []
        result = machine_module.diagnose(_ctx(structure))
        assert "ATS·区块缺失" in _categories(result)


# ============ FR-08 岗位匹配度 ============

JD_TEXT = """后端开发工程师
任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟练掌握 Python，熟悉 FastAPI 或 Django 框架；
3. 熟悉 MySQL、Redis，了解 Docker 与 CI/CD 流程；
4. 具备良好的沟通能力与团队协作精神；
5. 3 年以上后端开发经验。"""


class TestMatchModule:
    def test_jd_key_extraction(self):
        keys = extract_jd_keys(JD_TEXT)
        assert "Python" in keys["skills"]
        assert "FastAPI" in keys["skills"]
        assert keys["degree_req"] == "本科"
        assert keys["degree_level"] == 2
        assert keys["years_req"] == 3

    def test_word_boundary_prevents_substring_false_positive(self):
        """回归用例：Django 含 "go"、MySQL 含 "sql"，
        若用普通子串匹配会把"要求 Go/SQL"误判为已覆盖，评分虚高。"""
        assert contains_term("熟悉 django 框架", "go") is False
        assert contains_term("使用 mysql 数据库", "sql") is False
        assert contains_term("熟悉 go 语言", "go") is True
        assert contains_term("了解 ci/cd 流程", "ci/cd") is True

    def test_jd_does_not_extract_go_from_django(self):
        keys = extract_jd_keys(JD_TEXT)
        assert "Go" not in keys["skills"]

    def test_three_verdicts_produced(self):
        jd = {"id": "jd-1", "title": "后端", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)}
        result = match_module.diagnose(_ctx(_clean_structure(), jd=jd))
        verdicts = {m["verdict"] for m in result.meta["matches"]}
        assert "covered" in verdicts
        assert "missing" in verdicts
        assert "Python" in [m["requirement"] for m in result.meta["matches"] if m["verdict"] == "covered"]

    def test_covered_requirement_has_evidence_location(self):
        """设计文档 4.4：已覆盖必须输出对应证据位置。"""
        jd = {"id": "jd-1", "title": "后端", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)}
        result = match_module.diagnose(_ctx(_clean_structure(), jd=jd))
        for m in result.meta["matches"]:
            if m["verdict"] == "covered":
                assert m["evidence"]

    def test_degree_mismatch_is_critical(self):
        jd = {"id": "jd-1", "title": "后端", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)}
        structure = _clean_structure()
        structure["education"][0]["degree"] = "大专"
        result = match_module.diagnose(_ctx(structure, jd=jd))
        degree_issues = [i for i in result.issues if i.category == "岗位匹配·学历不符"]
        assert degree_issues and degree_issues[0].severity == SEVERITY_CRITICAL

    def test_missing_skill_is_major_with_hint(self):
        jd = {"id": "jd-1", "title": "后端", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)}
        result = match_module.diagnose(_ctx(_clean_structure(), jd=jd))
        gap_issues = [i for i in result.issues if i.category == "岗位匹配·技能缺失"]
        assert gap_issues and all(i.severity == SEVERITY_MAJOR for i in gap_issues)
        # 缺口必须区分"可短期补充"与"需长期积累"
        hints = {m.get("hint") for m in result.meta["matches"] if m["verdict"] == "missing"}
        assert any(h for h in hints)

    def test_score_formula_uses_hard_requirements_only(self):
        """软素质不计入匹配评分（它们不构成岗位硬门槛）；硬性要求按 kind 加权。"""
        jd = {"id": "jd-1", "title": "后端", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)}
        result = match_module.diagnose(_ctx(_clean_structure(), jd=jd))
        weights = {"skill": 1.0, "degree": 2.0, "years": 1.5}
        total = earned = 0.0
        for m in result.meta["matches"]:
            w = weights.get(m["kind"])
            if w is None:  # 软素质不计权
                continue
            total += w
            if m["verdict"] == "covered":
                earned += w
            elif m["verdict"] == "partial":
                earned += w * 0.5
        assert result.score == round(earned / total * 100)


# ============ 诊断编排与报告整合 ============

class TestRunner:
    def test_default_dimensions_exclude_match_without_jd(self):
        results = run_diagnosis("r", _clean_structure())
        dims = {r.dimension for r in results}
        assert DIM_MATCH not in dims
        assert {DIM_NORM, DIM_CONTENT, DIM_MACHINE} <= dims

    def test_health_score_excludes_match_dimension(self):
        """健康分只汇总"简历本身好不好"的三个维度；匹配分取决于岗位，不计入。"""
        structure = _clean_structure()
        quality = run_diagnosis("r", structure)
        with_match = run_diagnosis(
            "r",
            structure,
            dimensions=[DIM_NORM, DIM_CONTENT, DIM_MACHINE, DIM_MATCH],
            jd={"id": "j", "raw_text": JD_TEXT, "extracted_keys": extract_jd_keys(JD_TEXT)},
        )
        assert health_score(quality) == health_score(with_match)

    def test_health_score_is_weighted(self):
        structure = _clean_structure()
        structure["experience"][0]["description"] = "吃苦耐劳，有团队精神"  # content 扣分
        results = run_diagnosis("r", structure)
        scores = {r.dimension: r.score for r in results}
        expected = round(
            scores[DIM_NORM] * 0.3 + scores[DIM_CONTENT] * 0.4 + scores[DIM_MACHINE] * 0.3
        )
        assert health_score(results) == expected

    def test_unknown_dimension_raises(self):
        with pytest.raises(ValueError):
            run_diagnosis("r", _clean_structure(), dimensions=["nonexistent"])

    def test_issue_sorting_puts_high_impact_easy_first(self):
        """FR-11：影响大且好改的排在最前。"""
        structure = _clean_structure()
        structure["basic_info"]["phone"] = None          # critical，但属于"难改"（要补内容）
        structure["experience"][0]["description"] = "负责接口开发, 使用 Python 完成部署。"  # minor 标点混用
        results = run_diagnosis("r", structure)
        report = build_report("r", results)
        groups = report["issue_summary"]["groups"]
        assert "high_impact_easy" in groups and "high_impact_hard" in groups
        # 标点混用是典型"影响小但好改"；联系方式缺失影响大但需用户补充信息
        easy_cats = {i["category"] for i in groups["high_impact_easy"]}
        hard_cats = {i["category"] for i in groups["high_impact_hard"]}
        assert "联系方式缺失" in hard_cats

    def test_report_structure_complete(self):
        results = run_diagnosis("r", _clean_structure())
        report = build_report("r", results)
        assert report["total_score"] == health_score(results)
        assert set(report["dimension_scores"]) == {
            DIM_NORM,
            DIM_CONTENT,
            DIM_MACHINE,
            DIM_STRUCTURE,
        }
        assert report["dimension_scores"][DIM_NORM]["counted_in_health"] is True
        # 结构与篇幅是弹性维度：单独呈现，不计入健康分（砍掉不影响三维度定义）
        assert report["dimension_scores"][DIM_STRUCTURE]["counted_in_health"] is False
        assert report["issue_summary"]["total"] == 0

    def test_end_to_end_reproducible(self):
        """NFR-08：上传同一份简历，两次诊断的 result_id 与分数必须一致。"""
        structure = _clean_structure()
        structure["basic_info"]["phone"] = None
        a = run_diagnosis("r", structure)
        b = run_diagnosis("r", structure)
        assert [r.result_id for r in a] == [r.result_id for r in b]
        assert [r.score for r in a] == [r.score for r in b]
