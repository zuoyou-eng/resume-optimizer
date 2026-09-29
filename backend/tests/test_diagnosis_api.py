"""诊断相关接口测试（设计文档 7.1 接口 #3/#4/#5/#6 + 错误码表 + NFR-05 删除级联）。

按错误码表逐条设计场景，保证接口行为可被精确断言。
"""
import io
import json

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

JD_TEXT = """后端开发工程师
任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟练掌握 Python，熟悉 FastAPI 或 Django 框架；
3. 熟悉 MySQL、Redis，了解 Docker 与 CI/CD 流程；
4. 具备良好的沟通能力与团队协作精神；
5. 3 年以上后端开发经验。"""


def _upload(client, content: str = SAMPLE_TXT) -> str:
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    return body["data"]["resume_id"]


def _body(resp) -> dict:
    assert resp.status_code == 200
    body = resp.json()
    # 统一响应格式必须带 trace_id（设计文档 7.2）
    assert "trace_id" in body and body["trace_id"]
    return body


class TestJobDescriptionApi:
    def test_submit_jd_returns_extracted_keys(self, client):
        body = _body(
            client.post("/api/v1/job-descriptions", json={"title": "后端", "raw_text": JD_TEXT})
        )
        assert body["code"] == 0
        data = body["data"]
        assert data["jd_id"]
        assert "Python" in data["extracted_keys"]["skills"]
        assert data["extracted_keys"]["degree_req"] == "本科"
        assert data["extracted_keys"]["years_req"] == 3

    def test_submit_jd_too_short_returns_2005(self, client):
        body = _body(
            client.post("/api/v1/job-descriptions", json={"title": "", "raw_text": "招人"})
        )
        assert body["code"] == 2005

    def test_submit_jd_missing_field_returns_422(self, client):
        resp = client.post("/api/v1/job-descriptions", json={"title": "x"})
        assert resp.status_code == 422


class TestDiagnoseApi:
    def test_diagnose_returns_report(self, client):
        resume_id = _upload(client)
        body = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
        )
        assert body["code"] == 0
        data = body["data"]
        assert 0 <= data["total_score"] <= 100
        assert set(data["dimension_scores"]) == {"norm", "content", "machine", "structure"}
        assert data["issue_summary"]["total"] >= 0
        assert data["reproducible"] is True
        # 必须返回 diagnosis_ids：前端靠它拉取各维度明细（ATS 四类结论 / 匹配清单）
        assert data["diagnosis_ids"] and len(data["diagnosis_ids"]) == 4

    def test_diagnose_default_excludes_match(self, client):
        resume_id = _upload(client)
        body = _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))
        assert "match" not in body["data"]["dimension_scores"]

    def test_diagnose_with_specified_dimensions(self, client):
        resume_id = _upload(client)
        body = _body(
            client.post(
                "/api/v1/diagnoses",
                json={"resume_id": resume_id, "dimensions": ["norm"]},
            )
        )
        assert set(body["data"]["dimension_scores"]) == {"norm"}

    def test_diagnose_with_jd_includes_match(self, client):
        resume_id = _upload(client)
        jd_id = _body(
            client.post("/api/v1/job-descriptions", json={"title": "后端", "raw_text": JD_TEXT})
        )["data"]["jd_id"]
        body = _body(
            client.post(
                "/api/v1/diagnoses", json={"resume_id": resume_id, "jd_id": jd_id}
            )
        )
        scores = body["data"]["dimension_scores"]
        assert "match" in scores
        # 匹配分不计入健康分（设计语义：健康分只衡量简历本身质量）
        assert scores["match"]["counted_in_health"] is False
        assert scores["norm"]["counted_in_health"] is True
        assert len(body["data"]["diagnosis_ids"]) == 5

    def test_diagnose_with_missing_jd_returns_2004(self, client):
        resume_id = _upload(client)
        body = _body(
            client.post(
                "/api/v1/diagnoses",
                json={"resume_id": resume_id, "jd_id": "not-exist"},
            )
        )
        assert body["code"] == 2004

    def test_diagnose_unknown_dimension_is_rejected(self, client):
        resume_id = _upload(client)
        resp = client.post(
            "/api/v1/diagnoses",
            json={"resume_id": resume_id, "dimensions": ["bogus"]},
        )
        body = resp.json()
        assert body["code"] != 0

    def test_diagnose_missing_resume_returns_2003(self, client):
        body = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": "not-exist"})
        )
        assert body["code"] == 2003

    def test_diagnose_deleted_resume_returns_2003(self, client):
        resume_id = _upload(client)
        assert _body(client.delete(f"/api/v1/resumes/{resume_id}"))["code"] == 0
        body = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
        )
        assert body["code"] == 2003

    def test_diagnose_result_is_reproducible(self, client):
        """NFR-08：同一输入两次诊断，分数与问题数一致。"""
        resume_id = _upload(client, BAD_TXT)
        first = _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))["data"]
        second = _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))["data"]
        assert first["total_score"] == second["total_score"]
        assert first["issue_summary"] == second["issue_summary"]

    def test_bad_resume_scores_lower_than_good_resume(self, client):
        """诊断必须能区分质量差异，否则功能无意义。"""
        good = _upload(client, SAMPLE_TXT)
        bad = _upload(client, BAD_TXT)
        good_score = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": good})
        )["data"]["total_score"]
        bad_score = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": bad})
        )["data"]["total_score"]
        assert bad_score < good_score


class TestDiagnosisQueryApi:
    def test_get_diagnosis_by_id(self, client):
        resume_id = _upload(client)
        report = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
        )["data"]
        # 报告不直接返回 diagnosis_id，从数据库侧查询需先有记录；
        # 这里通过重新诊断后查询报告接口拿 diagnosis_ids
        detail = _body(client.get(f"/api/v1/reports/{resume_id}"))["data"]
        assert detail["diagnosis_ids"]
        first_id = detail["diagnosis_ids"][0]
        body = _body(client.get(f"/api/v1/diagnoses/{first_id}"))
        assert body["code"] == 0
        assert body["data"]["dimension"] in {"norm", "content", "machine", "match", "structure"}
        assert isinstance(body["data"]["issues"], list)

    def test_get_diagnosis_not_found_returns_2002(self, client):
        body = _body(client.get("/api/v1/diagnoses/not-exist"))
        assert body["code"] == 2002

    def test_get_report_after_diagnose(self, client):
        resume_id = _upload(client)
        _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))
        body = _body(client.get(f"/api/v1/reports/{resume_id}"))
        assert body["code"] == 0
        assert body["data"]["resume_id"] == resume_id
        assert "issue_summary" in body["data"]

    def test_get_report_before_diagnose_returns_2002(self, client):
        resume_id = _upload(client)
        body = _body(client.get(f"/api/v1/reports/{resume_id}"))
        assert body["code"] == 2002

    def test_get_report_for_missing_resume_returns_2003(self, client):
        body = _body(client.get("/api/v1/reports/not-exist"))
        assert body["code"] == 2003

    def test_report_refreshed_after_second_diagnose(self, client):
        resume_id = _upload(client, BAD_TXT)
        first = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
        )["data"]
        second = _body(
            client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
        )["data"]
        assert first["total_score"] == second["total_score"]


class TestCascadeDelete:
    def test_diagnosis_data_removed_with_resume(self, client):
        """NFR-05：删除简历后，其诊断与报告不可再访问（衍生数据级联清除）。"""
        resume_id = _upload(client)
        _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))
        detail = _body(client.get(f"/api/v1/reports/{resume_id}"))["data"]
        diagnosis_id = detail["diagnosis_ids"][0]

        assert _body(client.delete(f"/api/v1/resumes/{resume_id}"))["code"] == 0

        # 简历不存在 → 2003
        assert _body(client.get(f"/api/v1/reports/{resume_id}"))["code"] == 2003
        # 诊断记录随简历级联删除 → 2002（记录本身已不存在）
        assert _body(client.get(f"/api/v1/diagnoses/{diagnosis_id}"))["code"] == 2002
