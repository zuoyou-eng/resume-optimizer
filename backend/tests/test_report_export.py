"""FR-13 报告导出接口测试。

按设计文档 7.1 接口 #7 设计场景：
  1. 完整导出：内容完整性（分数 / 维度 / 问题 / ATS 结论 / 匹配明细 / 免责声明）与响应头；
  2. 负面路径：未诊断（2002）、简历不存在或已删除（2003）；
  3. 安全底线：简历内容中的 HTML/脚本字符必须被转义（防注入、防结构破坏）；
  4. 自包含：不引用任何外部资源，单文件可离线打开；
  5. 分组顺序与界面一致（FR-11 三组，导出层不重新排序）。
"""
import io
import re
from html import escape

import pytest

SAMPLE_TXT = """张三
电话：13812345678
邮箱：zhangsan@example.com
求职意向：后端开发工程师（杭州）

教育背景
浙江大学 计算机科学与技术 本科 2020.09-2024.06

实习经历
字节跳动科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发，使用 Python 与 MySQL，日均支撑 10 万次调用

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000

专业技能
熟练掌握 Python、Java、MySQL

荣誉奖项
校级优秀学生奖学金（2022）
"""

BAD_TXT = """李四
电话：10123456789

教育背景
某大学 本科 2021.09-2025.06

实习经历
某公司 实习生 2024.06-2024.12
吃苦耐劳，抗压能力强，有团队精神

专业技能
Python
"""

XSS_TXT = """王五
电话：13800138000
邮箱：wangwu@example.com

教育背景
南京大学 软件工程 本科 2021.09-2025.06

实习经历
<script>alert('xss')</script>科技有限公司 后端实习生 2023.06-2023.12
负责<b>接口</b>开发，吃苦耐劳
"""

JD_TEXT = """后端开发工程师
任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟练掌握 Python，熟悉 FastAPI 或 Django 框架；
3. 3 年以上后端开发经验。
"""


def _upload(client, text: str) -> str:
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["resume_id"]


def _diagnose(client, resume_id: str, jd: bool = False) -> dict:
    jd_id = None
    if jd:
        jd_resp = client.post(
            "/api/v1/job-descriptions",
            json={"title": "后端开发工程师", "raw_text": JD_TEXT},
        )
        jd_id = jd_resp.json()["data"]["jd_id"]
    resp = client.post(
        "/api/v1/diagnoses",
        json={"resume_id": resume_id, "jd_id": jd_id},
    )
    assert resp.status_code == 200
    return resp.json()["data"]


def _export(client, resume_id: str):
    return client.get(f"/api/v1/reports/{resume_id}/export")


class TestReportExport:
    def test_export_full_report(self, client):
        """完整导出：响应头、内容完整性（分数/维度/问题/ATS/免责声明）。"""
        rid = _upload(client, BAD_TXT)
        report = _diagnose(client, rid, jd=True)

        resp = _export(client, rid)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        # 附件下载语义 + 文件名可预期
        assert "attachment" in resp.headers["content-disposition"]
        assert re.search(r'diagnosis-report-[0-9a-f]{8}\.html', resp.headers["content-disposition"])

        html = resp.text
        # 健康分与问题总数来自报告层，逐字出现在导出件中
        assert str(report["total_score"]) in html
        assert str(report["issue_summary"]["total"]) in html
        # 四个维度全部呈现（含不计入健康分的匹配维度）
        for dim_key in ("norm", "content", "machine", "match"):
            assert dim_key in html
        # 每条问题的问题描述、建议、判定依据都必须导出（原则三：可核对）。
        # 导出层会做 HTML 转义，断言时同样转义后再比对。
        for issue in report["issues"]:
            assert escape(issue["problem"][:20]) in html
            assert escape(issue["suggestion"][:20]) in html
            if issue.get("evidence"):
                assert escape(issue["evidence"][:20]) in html
        # ATS 四类结论 + 岗位匹配区块
        assert "正确读取" in html and "field_verdicts" in html
        assert "岗位匹配明细" in html and "已覆盖" in html
        # 三条产品红线语义必须出现在报告里
        assert "不替用户编造内容" in html
        assert "影响大 · 好改" in html and "影响大 · 难改" in html and "影响小" in html

    def test_export_group_order_matches_report(self, client):
        """分组顺序与界面一致：01 → 02 → 03，导出层不重新排序。"""
        rid = _upload(client, BAD_TXT)
        _diagnose(client, rid)
        html = _export(client, rid).text
        pos_easy = html.find("影响大 · 好改")
        pos_hard = html.find("影响大 · 难改")
        pos_low = html.find("影响小")
        assert -1 < pos_easy < pos_hard < pos_low

    def test_export_without_jd_has_no_match_section(self, client):
        """未提交 JD 时不出岗位匹配区块（不误导用户）。"""
        rid = _upload(client, SAMPLE_TXT)
        _diagnose(client, rid)
        html = _export(client, rid).text
        assert "岗位匹配明细" not in html
        assert "不计入健康分" in html  # 语义说明仍在

    def test_export_escapes_resume_content(self, client):
        """安全底线：简历中的 HTML/脚本字符必须转义，不得注入报告。"""
        rid = _upload(client, XSS_TXT)
        _diagnose(client, rid)
        html = _export(client, rid).text
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html
        assert "<b>接口</b>" not in html  # 原文标签被转义而非渲染

    def test_export_is_self_contained(self, client):
        """自包含：无外部脚本/样式/字体引用，单文件可离线打开。"""
        rid = _upload(client, SAMPLE_TXT)
        _diagnose(client, rid)
        html = _export(client, rid).text
        assert "<script src" not in html
        assert "<link" not in html
        assert "http://" not in html and "https://" not in html
        assert "<style>" in html  # 样式内联

    def test_export_requires_diagnosis(self, client):
        """未诊断的简历不能导出报告（2002）。"""
        rid = _upload(client, SAMPLE_TXT)
        resp = _export(client, rid)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 2002
        assert body["trace_id"]

    def test_export_resume_not_found(self, client):
        """简历不存在 → 2003。"""
        resp = _export(client, "no-such-resume-id")
        assert resp.status_code == 200
        assert resp.json()["code"] == 2003

    def test_export_after_delete_returns_2003(self, client):
        """软删除后不可再导出（NFR-05：删除后不可再访问）。"""
        rid = _upload(client, SAMPLE_TXT)
        _diagnose(client, rid)
        assert _export(client, rid).status_code == 200
        del_resp = client.delete(f"/api/v1/resumes/{rid}")
        assert del_resp.status_code == 200
        resp = _export(client, rid)
        assert resp.json()["code"] == 2003
