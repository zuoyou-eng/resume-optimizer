"""结构化引擎单元测试（设计文档 8.2：固定输入 → 期望输出，无需启动服务）。"""
from app.config import settings
from app.parser.structurer import structure_document


class TestStructure:
    def test_basic_info_extraction(self):
        lines = [
            "张三",
            "电话：13812345678",
            "邮箱：zhangsan@example.com",
            "求职意向：后端开发工程师（杭州）",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        basic = result.structure["basic_info"]
        assert basic["email"] == "zhangsan@example.com"
        assert basic["phone"] == "13812345678"
        assert basic["name"] == "张三"
        assert basic["city"] == "杭州"

    def test_phone_and_email_on_same_line(self):
        """回归：电话与邮箱在同一行时，两者都必须取出，不能取到第一个就停。

        旧实现命中邮箱后 continue，同行的手机号被静默丢弃——
        违反 FR-03「严禁静默丢失」。图片 OCR 链路尤其容易触发
        （OCR 常把同行内容连成一行）。
        """
        lines = [
            "王五",
            "电话：13800138000 邮箱：wangwu@example.com",
            "教育背景",
            "南京大学 软件工程 本科 2021.09-2025.06",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        basic = result.structure["basic_info"]
        assert basic["phone"] == "13800138000"
        assert basic["email"] == "wangwu@example.com"
        assert basic["name"] == "王五"
        # 取到联系信息的行应被标记为已消费，不会被误判成姓名或章节
        assert "教育背景" in [t["field"] for t in result.trace] or any(
            t["field"].startswith("section.") for t in result.trace
        )

    def test_section_splitting_and_entries(self):
        lines = [
            "张三",
            "教育背景",
            "浙江大学 计算机科学与技术 本科 2020.09-2024.06",
            "实习经历",
            "字节跳动科技有限公司 后端开发实习生 2023.06-2023.12",
            "负责订单服务接口开发，使用 Python 与 MySQL",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        edu = result.structure["education"]
        assert len(edu) == 1
        assert edu[0]["school"] == "浙江大学"
        assert edu[0]["degree"] == "本科"
        assert edu[0]["period"] == "2020.09-2024.06"

        exp = result.structure["experience"]
        assert len(exp) == 1
        assert exp[0]["company"] == "字节跳动科技有限公司"
        assert exp[0]["role"] == "后端开发实习生"
        assert "订单服务" in exp[0]["description"]

    def test_skills_split(self):
        lines = ["专业技能", "熟练掌握 Python、Java、MySQL", "熟悉 Redis、Docker"]
        result = structure_document(lines, settings.RULE_VERSION)
        skills = result.structure["skills"]
        assert "Python" in skills and "Java" in skills
        assert "MySQL" in skills and "Redis" in skills and "Docker" in skills
        # 前缀动词不应混入技能名
        assert not any(s.startswith("熟练") for s in skills)

    def test_honors_one_per_line(self):
        lines = ["荣誉奖项", "1. 校级优秀学生奖学金（2022）", "全国大学生程序设计竞赛省二等奖"]
        result = structure_document(lines, settings.RULE_VERSION)
        honors = result.structure["honors"]
        assert len(honors) == 2
        assert honors[0] == "校级优秀学生奖学金（2022）"

    def test_unrecognized_content_not_lost(self):
        """FR-03：无法归类的原文必须显式出现在 unrecognized 中，严禁静默丢失。"""
        lines = [
            "张三",
            "教育背景",
            "浙江大学 计算机科学与技术 本科 2020.09-2024.06",
            "个人爱好广泛，喜欢阅读与跑步，保持每周三次运动习惯。",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        texts = [u["text"] for u in result.unrecognized]
        assert any("跑步" in t for t in texts)
        assert all("reason" in u for u in result.unrecognized)

    def test_no_silent_loss_total_coverage(self):
        """每一行要么被结构消费、要么出现在 unrecognized，不允许消失。"""
        lines = [
            "李四",
            "邮箱：lisi@example.com",
            "教育背景",
            "北京大学 软件工程 硕士 2019.09-2022.06",
            "一段完全无法归类的自由文本。",
            "另一段无法归类的自由文本。",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        trace_fields = {t["field"] for t in result.trace}
        unrecognized_texts = {u["text"] for u in result.unrecognized}
        # 邮箱行被消费
        assert "basic_info.email" in trace_fields
        # 两段自由文本都未丢失
        assert len(unrecognized_texts) == 2

    def test_determinism_same_input_same_output(self):
        """NFR-08：相同输入 → 相同输出（规则引擎天然确定，此处作为回归断言）。"""
        lines = [
            "王五",
            "电话：13900001111",
            "实习经历",
            "某科技公司 测试开发实习生 2024.01-2024.06",
            "编写自动化测试用例 200+ 条",
        ]
        r1 = structure_document(lines, settings.RULE_VERSION)
        r2 = structure_document(lines, settings.RULE_VERSION)
        assert r1.structure == r2.structure
        assert r1.trace == r2.trace
        assert r1.unrecognized == r2.unrecognized

    def test_trace_records_rule_and_source(self):
        """设计文档 4.3：解析轨迹必须包含命中的规则与来源区域。"""
        lines = ["赵六", "邮箱：zhaoliu@example.com"]
        result = structure_document(lines, settings.RULE_VERSION)
        email_trace = [t for t in result.trace if t["field"] == "basic_info.email"][0]
        assert email_trace["rule_applied"] == "regex:email"
        assert email_trace["source_region"]
        assert email_trace["verdict"] == "parsed"

    def test_school_with_city_prefix_not_misread(self):
        """回归：'南京大学'不能被城市正则误判为城市信息行（该行必须进入教育章节）。"""
        lines = [
            "李四",
            "邮箱：lisi@example.com",
            "教育背景",
            "南京大学 软件工程 本科 2021.09-2025.06",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        assert len(result.structure["education"]) == 1
        assert result.structure["education"][0]["school"] == "南京大学"
        assert result.structure["education"][0]["degree"] == "本科"
        # 该行不应被当作城市消费，城市应仍为未识别
        assert result.structure["basic_info"]["city"] is None

    def test_english_resume_sections(self):
        """回归：英文章节标题、英文姓名、英文条目应被正确识别。"""
        lines = [
            "Wang Wu",
            "Email: wangwu@example.com",
            "EDUCATION",
            "Tsinghua University Computer Science Bachelor 2019.09-2023.06",
            "EXPERIENCE",
            "Ali Cloud Tech Backend Developer Intern 2022.06-2022.12",
        ]
        result = structure_document(lines, settings.RULE_VERSION)
        assert result.structure["basic_info"]["name"] == "Wang Wu"
        assert len(result.structure["education"]) == 1
        assert result.structure["education"][0]["school"] == "Tsinghua University"
        assert result.structure["education"][0]["degree"].lower() == "bachelor"
        exp = result.structure["experience"]
        assert len(exp) == 1
        assert exp[0]["company"] == "Ali Cloud Tech"
        assert exp[0]["role"] == "Backend Developer Intern"

    def test_empty_input(self):
        result = structure_document([], settings.RULE_VERSION)
        assert result.structure["basic_info"]["name"] is None
        assert result.unrecognized == []
