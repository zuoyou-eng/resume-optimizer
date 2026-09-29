"""FR-09 引导式亮点挖掘测试（纯逻辑 + 接口两层）。

固化需求点名的三条红线：
  1. **只用用户提供的事实**——合成文本的事实必须全部来自「原文 + 用户答案」，
     违反则拒绝输出（6002），且违规内容不出现在成功响应里；
  2. **未经确认不写入**——compose 只产预览，confirm 才落库并产生新版本；
  3. **可跳过，不逼编造**——任何一层可跳过，跳过的层只进 missing_layers 提示。

另覆盖：字段白名单（只允许经历类描述）、候选清单复用 FR-05 结论、
NFR-08 可复现、NFR-10 版本快照。
"""
import io

import pytest

from app.optimize.highlight import (
    LAYER_ACTION,
    LAYER_EVIDENCE,
    LAYER_QUANT,
    LAYER_RESULT,
    build_questions,
    compose,
    field_label,
    verify_facts,
)

# 含"空话套话 + 表达力度弱"的平淡经历，用于触发候选与追问
FLAT_RESUME = """王五
电话：13800138000
邮箱：wangwu@example.com

教育背景
南京大学 软件工程 本科 2021年9月-2025年6月

实习经历
某科技有限公司 后端开发实习生 2023.06-2023.12
参与了订单服务接口开发，吃苦耐劳，抗压能力强

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000

专业技能
熟练掌握 Python、Java、MySQL
"""

COMPLETE_DESC = "设计并开发订单服务接口，基于 Python 与 MySQL，日均支撑 10 万次调用，接口错误率降至 0.3%"


# ============ 纯逻辑：问题生成 ============

class TestBuildQuestions:
    def test_complete_description_only_asks_evidence(self):
        qs = build_questions(COMPLETE_DESC)
        layers = [q.layer for q in qs]
        assert LAYER_EVIDENCE in layers
        assert LAYER_ACTION not in layers
        assert LAYER_QUANT not in layers
        assert LAYER_RESULT not in layers

    def test_flat_description_asks_action_and_quant(self):
        qs = build_questions("参与了订单服务接口开发")
        layers = [q.layer for q in qs]
        assert LAYER_ACTION in layers  # 句首弱参与表述触发动作追问
        assert LAYER_QUANT in layers
        assert LAYER_RESULT in layers

    def test_needed_flags_mark_missing_elements(self):
        qs = build_questions("参与了订单服务接口开发")
        needed = {q.layer: q.needed for q in qs}
        assert needed[LAYER_ACTION] is True
        assert needed[LAYER_EVIDENCE] is False  # 佐证层永远可选

    def test_every_question_carries_hint_and_example(self):
        for q in build_questions("写了一点东西"):
            assert q.question and q.hint and q.example

    def test_quantified_description_skips_quant_question(self):
        qs = build_questions("开发订单接口，日均 10 万次调用，错误率降至 0.3%")
        assert LAYER_QUANT not in [q.layer for q in qs]


# ============ 纯逻辑：合成 ============

class TestCompose:
    def test_compose_assembles_original_and_answers(self):
        result = compose("参与了订单服务接口开发", {LAYER_ACTION: "负责订单模块的接口设计与开发"})
        assert result.status == "composed"
        assert "负责订单模块的接口设计与开发" in result.after
        # 用户答了动作层 → 授权剥掉句首弱词
        assert "参与了" not in result.after
        assert result.after.endswith("。")

    def test_skipped_layers_not_composed_in(self):
        result = compose(
            "参与了订单服务接口开发",
            {LAYER_ACTION: "负责订单模块开发", LAYER_QUANT: "覆盖 3 条业务线"},
        )
        assert result.status == "composed"
        assert "覆盖 3 条业务线" in result.after
        # 结果层未答 → 不出现在合成文本，只进 missing_layers
        assert LAYER_RESULT in result.missing_layers

    def test_segments_carry_source_labels(self):
        result = compose(
            "开发订单接口",
            {LAYER_ACTION: "负责订单模块开发", LAYER_EVIDENCE: "输出接口文档 1 份"},
        )
        sources = {s["source"] for s in result.segments}
        assert "original" in sources
        assert LAYER_ACTION in sources
        assert LAYER_EVIDENCE in sources

    def test_duplicate_answer_not_repeated(self):
        result = compose(
            "负责订单服务接口开发",
            {LAYER_ACTION: "负责订单服务接口开发"},
        )
        assert result.after.count("负责订单服务接口开发") == 1

    def test_no_answers_keeps_original(self):
        result = compose("负责订单服务接口开发，使用 Python", {})
        assert result.status == "composed"
        assert "负责订单服务接口开发" in result.after

    def test_rejected_when_original_facts_lost(self):
        """原文的事实被答案"覆盖吞掉"时拒绝输出——宁可失败不丢事实。"""
        result = compose(
            "负责订单服务接口开发，使用 Python 与 MySQL，日均支撑 10 万次调用",
            {LAYER_ACTION: "负责订单服务接口开发"},
        )
        # 答案与原文前缀一致 → 去重判定吞掉整段原文 → 10 万次调用丢失 → 必须拒绝
        assert result.status == "rejected"
        assert result.after == ""
        assert result.reason
        assert result.fact_check["violated"]  # 丢失的事实被点名

    def test_fact_check_passed_on_normal_compose(self):
        result = compose("参与了订单服务接口开发", {LAYER_QUANT: "日均 10 万次调用"})
        assert result.fact_check["passed"] is True
        assert result.fact_check["added"] == []
        assert result.fact_check["violated"] == []


# ============ 纯逻辑：事实守恒 ============

class TestVerifyFacts:
    def test_answer_facts_are_allowed(self):
        """用户答案里的事实属于允许集合（用户显式授权引入）。"""
        report = verify_facts("开发订单接口", {LAYER_QUANT: "日均 10 万次调用"}, "开发订单接口；日均 10 万次调用。")
        assert report.passed is True

    def test_facts_outside_original_and_answers_rejected(self):
        """原文与答案之外的结构化事实（数字）必须被点名拒绝。"""
        report = verify_facts("开发订单接口", {}, "开发订单接口，管理 200 台服务器。")
        assert report.passed is False
        assert report.added  # 新增事实必须被点名

    def test_reproducible_same_input_same_output(self):
        args = ("参与了订单服务接口开发", {LAYER_ACTION: "负责订单模块开发"})
        first = compose(*args).to_dict()
        second = compose(*args).to_dict()
        assert first == second


class TestFieldLabel:
    def test_experience_label(self):
        assert field_label("experience[0].description") == "实习经历 · 第 1 条"

    def test_projects_label(self):
        assert field_label("projects[2].description") == "项目经历 · 第 3 条"


# ============ 接口层 ============

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


def _draft(client, resume_id: str) -> dict:
    return _body(client.get(f"/api/v1/resumes/{resume_id}/draft"))["data"]


def _revisions(client, draft_id: str) -> list[dict]:
    return _body(client.get(f"/api/v1/drafts/{draft_id}/revisions"))["data"]["revisions"]


class TestHighlightApi:
    def test_candidates_reuse_content_diagnosis(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            data = _body(
                client.get(f"/api/v1/resumes/{rid}/highlight-candidates")
            )["data"]
            assert data["candidate_count"] >= 1
            fields = [c["field_name"] for c in data["candidates"]]
            # 只允许经历类描述字段（服务层白名单）
            assert all(f.startswith(("experience[", "projects[")) for f in fields)
            # 每个候选带条目名称与命中的问题类别
            first = data["candidates"][0]
            assert first["item_title"]
            assert first["categories"]

    def test_questions_generated_for_experience_field(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            data = _body(
                client.post(
                    "/api/v1/highlights/questions",
                    json={"resume_id": rid, "field_name": "experience[0].description"},
                )
            )["data"]
            assert data["field_name"] == "experience[0].description"
            assert data["current_value"]
            layers = [q["layer"] for q in data["questions"]]
            assert LAYER_ACTION in layers  # "参与了…"触发动作追问
            assert LAYER_EVIDENCE in layers  # 佐证层恒在

    def test_non_experience_field_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            resp = client.post(
                "/api/v1/highlights/questions",
                json={"resume_id": rid, "field_name": "skills[0]"},
            )
            assert resp.status_code == 200
            assert resp.json()["code"] != 0  # 6001：字段白名单外

    def test_compose_does_not_persist(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            # 追问与预览都只走 _get_or_create_draft（flush 不 commit）
            _body(
                client.post(
                    "/api/v1/highlights/questions",
                    json={"resume_id": rid, "field_name": "experience[0].description"},
                )
            )
            data = _body(
                client.post(
                    "/api/v1/highlights/compose",
                    json={
                        "resume_id": rid,
                        "field_name": "experience[0].description",
                        "answers": {LAYER_ACTION: "负责订单模块的接口设计与开发"},
                    },
                )
            )["data"]
            assert data["status"] == "composed"
            # 红线 2：预览不落库——连草稿都不存在（事务回滚，无任何持久化）
            draft_after = _draft(client, rid)
            assert draft_after["draft_id"] is None
            assert draft_after["fields"] == []

    def test_confirm_writes_draft_and_creates_revision(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            # 确认前无任何草稿
            assert _draft(client, rid)["draft_id"] is None
            data = _body(
                client.post(
                    "/api/v1/highlights/confirm",
                    json={
                        "resume_id": rid,
                        "field_name": "experience[0].description",
                        "after_text": "负责订单模块的接口设计与开发；日均支撑 10 万次调用。",
                        "answers": {
                            LAYER_ACTION: "负责订单模块的接口设计与开发",
                            LAYER_QUANT: "日均支撑 10 万次调用",
                        },
                    },
                )
            )["data"]
            assert data["current_version"] >= 1
            assert "负责订单模块的接口设计与开发" in data["value"]
            assert data["fact_check"]["passed"] is True
            # 确认后才落库：草稿创建（init 首版快照）+ 亮点写入（highlight）
            draft = _draft(client, rid)
            assert draft["draft_id"]
            revisions = _revisions(client, draft["draft_id"])
            # 列表按时间倒序（最新在前），按 revision_no 排序后应为 init → highlight
            ops = [r["operation"] for r in sorted(revisions, key=lambda r: r["revision_no"])]
            assert ops == ["init", "highlight"]
            assert revisions[0]["operation"] == "highlight"  # 倒序契约：最新在前
            # 草稿里的字段值确实是写入后的值
            field = next(
                f for f in draft["fields"] if f["field_name"] == "experience[0].description"
            )
            assert "负责订单模块的接口设计与开发" in field["value"]
            assert field["source"] == "highlight"

    def test_confirm_rejects_fabricated_content(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            rid = _upload(client, FLAT_RESUME)
            resp = client.post(
                "/api/v1/highlights/confirm",
                json={
                    "resume_id": rid,
                    "field_name": "experience[0].description",
                    "after_text": "负责订单模块开发，管理 200 台服务器。",
                    "answers": {LAYER_ACTION: "负责订单模块开发"},
                },
            )
            # 红线 1：服务端复核拒绝写入
            assert resp.status_code == 200
            assert resp.json()["code"] != 0  # 6002
            # 拒绝路径不留下任何脏数据：草稿不应被创建
            draft_after = _draft(client, rid)
            assert draft_after["draft_id"] is None

    def test_unknown_resume_rejected(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/v1/resumes/not-exist-id/highlight-candidates")
            assert resp.status_code == 200
            assert resp.json()["code"] != 0  # 2003
