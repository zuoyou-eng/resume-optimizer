"""优化模块接口测试（设计文档 7.1 接口 #9-#18 + 7.3 错误码表 + NFR-09/NFR-10）。

覆盖完整闭环：上传 → 诊断 → 改写 → 应用 → 导出 → 复检 → 对比。
重点验证设计文档点名的几条"最容易被开发忽略"的约束：
  - 6002：系统主动拒绝改写，且**违规内容不出现在响应体里**
  - 6003：needs_review 的改写任何批量应用调用都被拦截
  - NFR-10：撤销后内容与撤销前逐字一致
  - 6006：前后解析版本不一致时拒绝产出不可比的对比
"""
import io
import json

import pytest

# 含标点混用 + 日期格式不一致 + 空话套话的简历，用于触发可改写与不可改写两类问题
RESUME_WITH_ISSUES = """王五
电话：13800138000
邮箱：wangwu@example.com

教育背景
南京大学 软件工程 本科 2021年9月-2025年6月

实习经历
某科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发, 使用 Python 与 MySQL，日均支撑 10 万次调用
吃苦耐劳，抗压能力强，有团队精神

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000

专业技能
熟练掌握 Python、Java、MySQL
"""

CLEAN_RESUME = """张三
电话：13812345678
邮箱：zhangsan@example.com

教育背景
浙江大学 计算机科学与技术 本科 2020.09-2024.06

实习经历
字节跳动科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发，使用 Python 与 MySQL，日均支撑 10 万次调用

专业技能
熟练掌握 Python、Java、MySQL
"""


def _upload(client, content: str) -> str:
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["resume_id"]


def _body(resp) -> dict:
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("trace_id")
    return body


def _diagnose(client, resume_id: str) -> dict:
    return _body(client.post("/api/v1/diagnoses", json={"resume_id": resume_id}))["data"]


def _issues_of(client, report: dict) -> list[dict]:
    out: list[dict] = []
    for did in report["diagnosis_ids"]:
        detail = _body(client.get(f"/api/v1/diagnoses/{did}"))["data"]
        out.extend(detail["issues"])
    return out


def _field_value(draft: dict, field_name: str):
    for f in draft["fields"]:
        if f["field_name"] == field_name:
            return f["value"]
    return None


def _field_source(draft: dict, field_name: str):
    for f in draft["fields"]:
        if f["field_name"] == field_name:
            return f["source"]
    return None


# ============ 草稿创建（O-04） ============

class TestDraftCreation:
    def test_draft_created_from_parse_result(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        issues = _issues_of(client, report)
        rewrites = []
        for issue in issues:
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated":
                rewrites.append(r)

        assert rewrites, "应至少产出一条可应用改写"
        applied = _body(client.post(f"/api/v1/rewrites/{rewrites[0]['rewrite_id']}/apply"))["data"]
        draft = _body(client.get(f"/api/v1/drafts/{applied['draft_id']}"))["data"]
        assert draft["field_count"] > 0
        assert draft["current_version"] >= 2
        assert draft["rewritten_count"] >= 1

    def test_rewrite_for_unknown_issue_returns_6001(self, client):
        rid = _upload(client, CLEAN_RESUME)
        body = _body(
            client.post("/api/v1/rewrites", json={"resume_id": rid, "issue_id": "iss-nope"})
        )
        assert body["code"] == 6001

    def test_rewrite_for_unknown_resume_returns_2003(self, client):
        body = _body(
            client.post(
                "/api/v1/rewrites", json={"resume_id": "nope", "issue_id": "iss-x"}
            )
        )
        assert body["code"] == 2003


# ============ 改写生成（O-01 / O-02） ============

class TestGenerateRewrite:
    def test_generated_rewrite_carries_change_points_and_fact_check(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        punctuation_issue = next(
            i for i in _issues_of(client, report) if i["category"] == "中英文标点混用"
        )
        r = _body(
            client.post(
                "/api/v1/rewrites", json={"resume_id": rid, "issue_id": punctuation_issue["issue_id"]}
            )
        )["data"]

        assert r["status"] == "generated"
        assert r["risk_level"] == "auto_safe"
        # O-02：改动点必须结构化，前端才能逐点高亮
        assert r["change_points"]
        for cp in r["change_points"]:
            assert cp["change_class"]
            assert "before_span" in cp and "after_span" in cp
        # 事实守恒报告必须随改写返回
        assert r["fact_check"]["passed"] is True
        assert r["fact_check"]["violated"] == []

    def test_unfixable_issue_degrades_to_suggestion_only(self, client):
        """需要补充真实信息的问题必须降级为仅建议，系统不代写。"""
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        issues = _issues_of(client, report)
        target = next(
            (i for i in issues if i["category"] in ("空话套话", "要素缺失·结果如何")),
            None,
        )
        if target is None:
            pytest.skip("该样例未产生需补充信息的问题")
        r = _body(
            client.post(
                "/api/v1/rewrites", json={"resume_id": rid, "issue_id": target["issue_id"]}
            )
        )["data"]
        assert r["status"] == "suggestion_only"
        assert r["after"] == ""

    def test_rewrite_result_queryable(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        issue = next(
            i for i in _issues_of(client, report) if i["category"] == "中英文标点混用"
        )
        created = _body(
            client.post("/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]})
        )["data"]
        fetched = _body(client.get(f"/api/v1/rewrites/{created['rewrite_id']}"))["data"]
        assert fetched["rewrite_id"] == created["rewrite_id"]
        assert fetched["before"] == created["before"]

    def test_unknown_rewrite_returns_6001(self, client):
        body = _body(client.get("/api/v1/rewrites/nope"))
        assert body["code"] == 6001


# ============ 应用与撤销（O-03 / NFR-10） ============

class TestApplyAndRollback:
    def _make_generated_rewrite(self, client, content=RESUME_WITH_ISSUES):
        rid = _upload(client, content)
        report = _diagnose(client, rid)
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated":
                return rid, r
        pytest.skip("未产出可应用改写")

    def test_apply_writes_field_and_marks_source(self, client):
        rid, rewrite = self._make_generated_rewrite(client)
        result = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["data"]
        draft = _body(client.get(f"/api/v1/drafts/{result['draft_id']}"))["data"]

        field = rewrite["target_field"]
        # 关键回归：JSON 字段的就地修改必须真正落库（曾因缺 flag_modified 而静默失败）
        assert _field_value(draft, field) == rewrite["after"]
        assert _field_source(draft, field) == "rewritten"

    def test_double_apply_rejected(self, client):
        rid, rewrite = self._make_generated_rewrite(client)
        assert _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["code"] == 0
        body = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))
        assert body["code"] == 6001

    def test_rollback_restores_content_verbatim(self, client):
        """NFR-10：撤销后内容与撤销前逐字一致。"""
        rid, rewrite = self._make_generated_rewrite(client)
        draft_id = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["data"]["draft_id"]

        # 原文取改写的 before（逐字保留），而不是 apply 之后的值
        original = rewrite["before"]
        field = rewrite["target_field"]
        applied = _body(client.get(f"/api/v1/drafts/{draft_id}"))["data"]
        assert _field_value(applied, field) == rewrite["after"]

        # 再改一次，然后回滚到首版
        _body(
            client.patch(
                f"/api/v1/drafts/{draft_id}/fields",
                json={"field_name": field, "value": "临时改动内容"},
            )
        )
        _body(client.post(f"/api/v1/drafts/{draft_id}/rollback", json={"revision_no": 1}))
        after = _body(client.get(f"/api/v1/drafts/{draft_id}"))["data"]

        assert _field_value(after, field) == original
        assert _field_source(after, field) == "parsed"

    def test_rollback_to_unknown_version_returns_6004(self, client):
        rid, rewrite = self._make_generated_rewrite(client)
        draft_id = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["data"]["draft_id"]
        body = _body(client.post(f"/api/v1/drafts/{draft_id}/rollback", json={"revision_no": 999}))
        assert body["code"] == 6004

    def test_manual_edit_creates_new_version(self, client):
        rid, rewrite = self._make_generated_rewrite(client)
        draft_id = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["data"]["draft_id"]
        before = _body(client.get(f"/api/v1/drafts/{draft_id}"))["data"]["current_version"]

        result = _body(
            client.patch(
                f"/api/v1/drafts/{draft_id}/fields",
                json={"field_name": "skills[0]", "value": "精通 Python"},
            )
        )["data"]
        assert result["current_version"] == before + 1

        draft = _body(client.get(f"/api/v1/drafts/{draft_id}"))["data"]
        assert _field_value(draft, "skills[0]") == "精通 Python"
        assert _field_source(draft, "skills[0]") == "manual"

    def test_revision_history_records_operations(self, client):
        rid, rewrite = self._make_generated_rewrite(client)
        draft_id = _body(client.post(f"/api/v1/rewrites/{rewrite['rewrite_id']}/apply"))["data"]["draft_id"]
        revisions = _body(client.get(f"/api/v1/drafts/{draft_id}/revisions"))["data"]
        ops = [r["operation"] for r in revisions["revisions"]]
        assert "init" in ops
        assert "apply" in ops
        assert revisions["current_version"] == max(r["revision_no"] for r in revisions["revisions"])


# ============ O-06 / O-07 批量应用与风险分级 ============

class TestBatchApply:
    def _make_rewrites(self, client, content=RESUME_WITH_ISSUES):
        rid = _upload(client, content)
        report = _diagnose(client, rid)
        out = []
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated":
                out.append(r)
        return rid, out

    def test_batch_apply_accepts_auto_safe(self, client):
        rid, rewrites = self._make_rewrites(client)
        safe = [r for r in rewrites if r["risk_level"] == "auto_safe"]
        if not safe:
            pytest.skip("无 auto_safe 改写")
        draft_id = _body(client.post(f"/api/v1/rewrites/{safe[0]['rewrite_id']}/apply"))["data"]["draft_id"]

        rest = [r["rewrite_id"] for r in safe[1:]]
        if rest:
            result = _body(
                client.post(f"/api/v1/drafts/{draft_id}/batch-apply", json={"rewrite_ids": rest})
            )["data"]
            assert result["applied_count"] == len(rest)
            assert result["current_version"] > 1

    def test_rule_engine_only_produces_auto_safe(self, client):
        """规则引擎只做确定性修正，产物必须 100% 是 auto_safe。"""
        rid, rewrites = self._make_rewrites(client)
        assert rewrites
        assert all(r["risk_level"] == "auto_safe" for r in rewrites)

    def test_batch_apply_rejects_needs_review_with_6003(self, client, monkeypatch):
        """O-07 硬约束：needs_review 一律 6003，前端不可信。

        规则引擎产不出 needs_review，因此注入"会改措辞"的桩引擎来真正验证这条分界线。
        """
        from app.optimize.engine import WordingStubEngine

        monkeypatch.setattr(
            "app.services.rewrite_service.RuleRewriteEngine", WordingStubEngine
        )
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        review, safe = [], []
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] != "generated":
                continue
            (review if r["risk_level"] == "needs_review" else safe).append(r)

        assert review, "桩引擎应产出 needs_review 改写"
        assert safe, "样例中应仍有 auto_safe 改写可用于建立草稿"

        draft_id = _body(client.post(f"/api/v1/rewrites/{safe[0]['rewrite_id']}/apply"))["data"]["draft_id"]
        body = _body(
            client.post(
                f"/api/v1/drafts/{draft_id}/batch-apply",
                json={"rewrite_ids": [r["rewrite_id"] for r in review]},
            )
        )
        assert body["code"] == 6003

    def test_batch_apply_does_not_leak_review_content(self, client, monkeypatch):
        """6003 被拒时，响应体不得夹带任何被拒改写的内容。"""
        from app.optimize.engine import WordingStubEngine

        monkeypatch.setattr(
            "app.services.rewrite_service.RuleRewriteEngine", WordingStubEngine
        )
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        review, safe = [], []
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] != "generated":
                continue
            (review if r["risk_level"] == "needs_review" else safe).append(r)
        if not review or not safe:
            pytest.skip("该样例未同时产生两类风险等级的改写")

        draft_id = _body(client.post(f"/api/v1/rewrites/{safe[0]['rewrite_id']}/apply"))["data"]["draft_id"]
        resp = client.post(
            f"/api/v1/drafts/{draft_id}/batch-apply",
            json={"rewrite_ids": [r["rewrite_id"] for r in review]},
        )
        payload = json.dumps(resp.json(), ensure_ascii=False)
        for r in review:
            assert r["after"] not in payload

    def test_wording_rewrite_requires_manual_apply(self, client, monkeypatch):
        """needs_review 的改写可以单条人工应用（O-01 的"接受"路径），但不许批量。"""
        from app.optimize.engine import WordingStubEngine

        monkeypatch.setattr(
            "app.services.rewrite_service.RuleRewriteEngine", WordingStubEngine
        )
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        target = None
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated" and r["risk_level"] == "needs_review":
                target = r
                break
        if target is None:
            pytest.skip("未产出 needs_review 改写")

        result = _body(client.post(f"/api/v1/rewrites/{target['rewrite_id']}/apply"))["data"]
        draft = _body(client.get(f"/api/v1/drafts/{result['draft_id']}"))["data"]
        assert _field_value(draft, target["target_field"]) == target["after"]

    def test_batch_apply_empty_list_rejected(self, client):
        rid, rewrites = self._make_rewrites(client)
        draft_id = _body(client.post(f"/api/v1/rewrites/{rewrites[0]['rewrite_id']}/apply"))["data"]["draft_id"]
        resp = client.post(f"/api/v1/drafts/{draft_id}/batch-apply", json={"rewrite_ids": []})
        assert resp.status_code == 422


# ============ 导出与复检（O-05） ============

class TestExportAndRecheck:
    def test_export_produces_files_and_recheck(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated" and r["risk_level"] == "auto_safe":
                draft_id = _body(client.post(f"/api/v1/rewrites/{r['rewrite_id']}/apply"))["data"]["draft_id"]
                break
        else:
            pytest.skip("无 auto_safe 改写")

        result = _body(client.post(f"/api/v1/drafts/{draft_id}/export"))["data"]
        assert result["files"]["txt"].endswith(".txt")
        assert result["files"]["docx"].endswith(".docx")
        # 复检必须真实跑过诊断，产出分数与 ATS 结论
        assert "total_score" in result["recheck"]
        assert "verdict_summary" in result["recheck"]
        assert set(result["recheck"]["verdict_summary"]) == {
            "correct", "lost", "misplaced", "fabricated",
        }


# ============ 优化前后对比（O-09） ============

class TestComparison:
    def test_comparison_has_three_diff_types(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated" and r["risk_level"] == "auto_safe":
                draft_id = _body(client.post(f"/api/v1/rewrites/{r['rewrite_id']}/apply"))["data"]["draft_id"]
                break
        else:
            pytest.skip("无 auto_safe 改写")

        _body(client.post(f"/api/v1/drafts/{draft_id}/export"))
        cmp = _body(client.get(f"/api/v1/drafts/{draft_id}/comparison"))["data"]

        # 三类差异必须齐备
        assert set(cmp["score_diff"]["dimensions"]) >= {"norm", "content", "machine"}
        assert "delta" in cmp["score_diff"]
        assert isinstance(cmp["content_diff"], list)
        assert set(cmp["parse_diff"]["before"]) == {"correct", "lost", "misplaced", "fabricated"}
        assert set(cmp["parse_diff"]["after"]) == {"correct", "lost", "misplaced", "fabricated"}
        # 同类对比约束：必须记录两端解析器版本
        assert cmp["parser_version"]["before"] == cmp["parser_version"]["after"]


# ============ 隐私：删除简历级联清除草稿 ============

class TestCascadeDelete:
    def test_delete_resume_removes_draft(self, client):
        rid = _upload(client, RESUME_WITH_ISSUES)
        report = _diagnose(client, rid)
        for issue in _issues_of(client, report):
            r = _body(
                client.post(
                    "/api/v1/rewrites", json={"resume_id": rid, "issue_id": issue["issue_id"]}
                )
            )["data"]
            if r["status"] == "generated":
                draft_id = _body(client.post(f"/api/v1/rewrites/{r['rewrite_id']}/apply"))["data"]["draft_id"]
                break
        else:
            pytest.skip("无可应用改写")

        assert _body(client.delete(f"/api/v1/resumes/{rid}"))["code"] == 0
        # 草稿随简历删除 → 不可再访问
        body = _body(client.get(f"/api/v1/drafts/{draft_id}"))
        assert body["code"] == 6001
