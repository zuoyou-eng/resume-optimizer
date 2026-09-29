"""FR-07 结构与篇幅体检模块单元测试。

固化三项设计决策（模块 docstring）：
  1. 身份推断不使用当前日期——相同输入永远得到相同身份结论（NFR-08）；
  2. 页数按文本量估算，估算依据写入 evidence/meta（判定透明）；
  3. 位置检查利用 trace 的文档顺序，无需重读原文件。

外加四个检查项的正反用例：模块完整性 / 页数匹配 / 篇幅占比 / 关键信息位置。
"""
from app.config import settings
from app.diagnosis.base import DiagnosisContext
from app.diagnosis.structure import (
    CHARS_PER_PAGE,
    CONTACT_DEPTH_RATIO,
    MAX_HONOR_RATIO,
    MIN_CORE_RATIO,
    MODULE as structure_module,
    RULE_VERSION,
    _infer_identity,
)
from app.parser.structurer import structure_document


def _ctx(structure=None, trace=None, unrecognized=None) -> DiagnosisContext:
    return DiagnosisContext(
        resume_id="r-struct",
        structure=structure or {},
        trace=trace or [],
        unrecognized=unrecognized or [],
    )


def _categories(result) -> set[str]:
    return {i.category for i in result.issues}


def _clean_structure() -> dict:
    """一页以内、结构完整的简历（与 test_diagnosis_modules 同源，保证口径一致）。"""
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


def _trace(*fields: str) -> list[dict]:
    """按给定顺序构造 trace（下标即文档顺序代理）。"""
    return [
        {"field": f, "extracted": "x", "source_region": "y", "rule_applied": "RE"}
        for f in fields
    ]


def _meta_without_elapsed(result: dict) -> dict:
    """剔除耗时字段后的 meta（NFR-08 比对结论用，耗时天然非确定）。"""
    return {k: v for k, v in (result.get("meta") or {}).items() if k != "elapsed_ms"}


class TestModuleCompleteness:
    """模块完整性：缺教育/经历是 critical，缺姓名是 major。"""

    def test_complete_structure_has_no_module_issue(self):
        result = structure_module.diagnose(_ctx(_clean_structure()))
        assert not _categories(result) & {
            "模块缺失·教育背景",
            "模块缺失·经历",
            "模块缺失·姓名",
        }

    def test_missing_education_is_critical(self):
        s = _clean_structure()
        s["education"] = []
        result = structure_module.diagnose(_ctx(s))
        issue = next(i for i in result.issues if i.category == "模块缺失·教育背景")
        assert issue.severity == "critical"
        assert issue.location.field == "education"
        assert issue.evidence  # 判定依据可查

    def test_missing_both_experience_and_projects_is_critical(self):
        s = _clean_structure()
        s["experience"] = []
        s["projects"] = []
        result = structure_module.diagnose(_ctx(s))
        issue = next(i for i in result.issues if i.category == "模块缺失·经历")
        assert issue.severity == "critical"

    def test_projects_alone_satisfies_experience_requirement(self):
        s = _clean_structure()
        s["experience"] = []
        result = structure_module.diagnose(_ctx(s))
        assert "模块缺失·经历" not in _categories(result)

    def test_missing_name_is_major(self):
        s = _clean_structure()
        s["basic_info"] = {k: v for k, v in s["basic_info"].items() if k != "name"}
        result = structure_module.diagnose(_ctx(s))
        issue = next(i for i in result.issues if i.category == "模块缺失·姓名")
        assert issue.severity == "major"


class TestIdentityInference:
    """身份推断：只用简历自身信号，不用当前日期（NFR-08）。"""

    def test_work_experience_implies_professional(self):
        s = _clean_structure()
        identity, basis = _infer_identity(s)
        assert identity == "professional"
        assert basis  # 判定依据非空

    def test_open_ended_education_period_implies_student(self):
        s = _clean_structure()
        s["experience"] = []
        s["projects"] = []
        s["education"][0]["period"] = "2022.09 至今"
        identity, _ = _infer_identity(s)
        assert identity == "student"

    def test_campus_experience_implies_student(self):
        s = _clean_structure()
        s["experience"] = [
            {"company": "校园经历", "role": "组织部干事", "period": "2021.09-2022.06"}
        ]
        s["projects"] = []
        identity, _ = _infer_identity(s)
        assert identity == "student"

    def test_junior_degree_without_experience_implies_student(self):
        s = _clean_structure()
        s["experience"] = []
        s["projects"] = []
        identity, _ = _infer_identity(s)
        assert identity == "student"

    def test_insufficient_signals_returns_unknown(self):
        s = {"basic_info": {"name": "张三"}, "education": [], "experience": []}
        identity, basis = _infer_identity(s)
        assert identity == "unknown"
        assert "身份信号不足" in basis

    def test_same_input_same_identity(self):
        """可复现性：连续两次推断必须一致（不使用当前日期的直接验证）。"""
        s = _clean_structure()
        first = _infer_identity(s)
        second = _infer_identity(s)
        assert first == second


class TestPageCount:
    """页数与身份匹配：学生 1 页 / 社招 2 页为上限，unknown 不判定。"""

    @staticmethod
    def _long_resume(identity: str) -> dict:
        """构造指定身份的超长简历（经历描述足够长以超过页数上限）。"""
        s = _clean_structure()
        if identity == "student":
            s["experience"] = []
            s["projects"] = []
            s["education"][0]["period"] = "2022.09 至今"
            # 用未识别内容把总篇幅推到 2 页以上
            return s
        return s

    def test_student_over_one_page_is_major(self):
        s = _clean_structure()
        s["experience"] = []
        s["projects"] = []
        s["education"][0]["period"] = "2022.09 至今"
        # 塞入超长荣誉把总字符推过 2 页（每页约 800 字）
        s["honors"] = ["荣誉" + "奖" * 40] * 45
        result = structure_module.diagnose(_ctx(s))
        issue = next(
            (i for i in result.issues if i.category == "页数与身份不匹配"), None
        )
        assert issue is not None
        assert issue.severity == "major"
        assert "应届生/学生" in issue.problem
        # 估算依据必须可查（设计决策 2）
        assert str(CHARS_PER_PAGE) in issue.evidence

    def test_professional_within_two_pages_has_no_issue(self):
        s = _clean_structure()
        s["honors"] = ["荣誉" + "奖" * 40] * 20  # 约 900 字，仍不足 2 页
        result = structure_module.diagnose(_ctx(s))
        assert "页数与身份不匹配" not in _categories(result)

    def test_unknown_identity_skips_page_check(self):
        s = {"basic_info": {"name": "张三"}, "education": [], "experience": []}
        s["honors"] = ["荣誉" + "奖" * 40] * 45
        result = structure_module.diagnose(_ctx(s))
        assert "页数与身份不匹配" not in _categories(result)
        assert result.meta["identity"] == "unknown"

    def test_meta_reports_estimation_inputs(self):
        s = _clean_structure()
        result = structure_module.diagnose(_ctx(s))
        assert result.meta["estimated_pages"] >= 1
        assert result.meta["total_chars"] > 0
        assert "identity_basis" in result.meta


class TestProportion:
    """篇幅占比：经历占比过低 major / 荣誉占比过高 minor，短简历不判定。"""

    def test_core_too_small_is_major(self):
        s = _clean_structure()
        s["skills"] = ["技能项" + "描述" * 8] * 30  # 技能膨胀，经历被稀释到 25% 以下
        result = structure_module.diagnose(_ctx(s))
        issue = next(
            (i for i in result.issues if i.category == "经历篇幅占比过低"), None
        )
        assert issue is not None
        assert issue.severity == "major"
        assert str(MIN_CORE_RATIO) in issue.evidence or "%" in issue.evidence

    def test_honor_overflow_is_minor(self):
        s = _clean_structure()
        s["honors"] = ["奖项名称" + "说明" * 10] * 12  # 荣誉占比超过 20%
        result = structure_module.diagnose(_ctx(s))
        issue = next(
            (i for i in result.issues if i.category == "荣誉占比过高"), None
        )
        assert issue is not None
        assert issue.severity == "minor"

    def test_short_resume_skips_proportion_check(self):
        """总篇幅不足阈值时不做占比判定——避免短简历被噪声支配。"""
        s = _clean_structure()
        s["skills"] = []
        s["honors"] = []
        s["experience"] = [{"company": "某公司", "role": "实习", "period": "2023.06-2023.12"}]
        s["projects"] = []
        result = structure_module.diagnose(_ctx(s))
        assert "经历篇幅占比过低" not in _categories(result)
        assert "荣誉占比过高" not in _categories(result)
        assert str(MAX_HONOR_RATIO) not in str(result.issues)


class TestKeyInfoPosition:
    """关键信息位置：联系方式过深 major / 姓名不在开头 minor / 开篇区块不当 minor。"""

    def test_contact_too_deep_is_major(self):
        trace = _trace(*[f"section.honors[{i}]" for i in range(9)])
        trace.append({"field": "basic_info.phone", "extracted": "138"})
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=trace))
        issue = next(
            (i for i in result.issues if i.category == "联系方式位置过深"), None
        )
        assert issue is not None
        assert issue.severity == "major"
        assert str(CONTACT_DEPTH_RATIO) in issue.evidence or "%" in issue.evidence

    def test_contact_in_head_has_no_issue(self):
        trace = _trace("basic_info.name", "basic_info.phone", "section.education")
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=trace))
        assert "联系方式位置过深" not in _categories(result)

    def test_name_not_at_top_is_minor(self):
        trace = _trace("basic_info.phone", "basic_info.email", "section.education")
        trace.append({"field": "basic_info.name", "extracted": "张三"})
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=trace))
        issue = next(
            (i for i in result.issues if i.category == "姓名位置不佳"), None
        )
        assert issue is not None
        assert issue.severity == "minor"

    def test_skills_first_section_is_minor(self):
        trace = _trace("basic_info.name", "basic_info.phone", "section.skills")
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=trace))
        issue = next(
            (i for i in result.issues if i.category == "开篇区块不当"), None
        )
        assert issue is not None
        assert issue.severity == "minor"
        assert "skills" in issue.evidence

    def test_education_first_section_is_fine(self):
        trace = _trace("basic_info.name", "basic_info.phone", "section.education")
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=trace))
        assert "开篇区块不当" not in _categories(result)

    def test_empty_trace_skips_position_checks(self):
        result = structure_module.diagnose(_ctx(_clean_structure(), trace=[]))
        assert "联系方式位置过深" not in _categories(result)
        assert "姓名位置不佳" not in _categories(result)
        assert "开篇区块不当" not in _categories(result)


class TestRealSampleNoFalsePositive:
    """真实样例简历（conftest 同源）→ 结构维度零误报。"""

    def test_clean_sample_resume_has_no_structure_issue(self):
        text = """张三
电话：13812345678
邮箱：zhangsan@example.com
求职意向：后端开发工程师（杭州）

教育背景
浙江大学 计算机科学与技术 本科 2020.09-2024.06
主修课程：数据结构、操作系统、计算机网络

实习经历
字节跳动科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发，使用 Python 与 MySQL
参与压测与线上问题排查，累计处理工单 50+ 单

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000
使用 Redis 缓存热点数据，接口耗时下降 60%

专业技能
熟练掌握 Python、Java、MySQL
熟悉 Redis、Docker、Linux 常用命令

荣誉奖项
校级优秀学生奖学金（2022）
全国大学生程序设计竞赛省二等奖
"""
        parsed = structure_document(text.splitlines(), settings.RULE_VERSION)
        result = structure_module.diagnose(
            _ctx(
                structure=parsed.structure,
                trace=parsed.trace,
                unrecognized=parsed.unrecognized,
            )
        )
        assert result.issues == [], [i.category for i in result.issues]


class TestReproducibility:
    """NFR-08：相同输入两次执行，结论与 meta 完全一致。"""

    def test_same_input_same_result(self):
        s = _clean_structure()
        s["education"] = []
        trace = _trace("basic_info.phone", "section.skills")
        first = structure_module.diagnose(_ctx(s, trace=trace)).to_dict()
        second = structure_module.diagnose(_ctx(s, trace=trace)).to_dict()
        assert first["issues"] == second["issues"]
        # elapsed_ms 是耗时测量值，天然非确定；NFR-08 约束的是结论（checks/结论字段），
        # 不含耗时。比对 meta 时剔除该键，否则偶发 0.2 vs 0.0 会造成假失败。
        assert _meta_without_elapsed(first) == _meta_without_elapsed(second)
        assert first["score"] == second["score"]

    def test_rule_version_on_result(self):
        result = structure_module.diagnose(_ctx(_clean_structure()))
        assert result.rule_version == RULE_VERSION
        assert result.module_name == "structure_layout"
