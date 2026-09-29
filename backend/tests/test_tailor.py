"""O-08 定制版本生成测试（纯逻辑 + 接口两层）。

固化需求红线「只做取舍与重组，不新增事实」：
  * 值多重集逐一守恒（服务端复核）；
  * 无移动不产生空版本；
  * 可回滚撤销（NFR-10）；
  * 无 match 诊断不可定制（6007）；
  * 确定性：相同输入 → 相同计划（NFR-08）。
"""
import io
from collections import Counter

import pytest

from app.optimize.tailor import plan_tailored

RESUME_TXT = """王五
电话：13800138000
邮箱：wangwu@example.com
求职意向：后端开发工程师

教育背景
南京大学 软件工程 本科 2021.09-2025.06

实习经历
某教育公司 助教 2022.06-2022.09
带暑期培训班，批改作业，维护学员群

某科技公司 后端开发实习生 2023.06-2023.12
使用 Python 与 FastAPI 开发后端接口，日均支撑 10 万次调用

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000

专业技能
Photoshop、Python、FastAPI、MySQL

荣誉奖项
校级优秀学生奖学金（2022）
"""

JD_TEXT = """后端开发工程师
任职要求：
1. 本科及以上学历，计算机相关专业；
2. 熟练掌握 Python，熟悉 FastAPI 或 Django 框架；
3. 熟悉 MySQL 数据库与 Redis 缓存；
4. 3 年以上后端开发经验。
"""

MATCH_META = {
    "jd_title": "后端开发工程师",
    "matches": [
        {"requirement": "Python", "kind": "skill", "verdict": "covered"},
        {"requirement": "FastAPI", "kind": "skill", "verdict": "covered"},
        {"requirement": "Django", "kind": "skill", "verdict": "missing"},
    ],
    "gaps": ["Django", "3 年以上后端开发经验"],
}


def _fields():
    return [
        {"field_name": "basic_info.name", "value": "王五", "source": "parsed", "version_no": 1},
        {"field_name": "basic_info.email", "value": "w@e.com", "source": "parsed", "version_no": 1},
        {"field_name": "education[0].school", "value": "南京大学", "source": "parsed", "version_no": 1},
        {"field_name": "education[0].degree", "value": "本科", "source": "parsed", "version_no": 1},
        {"field_name": "experience[0].company", "value": "某教育公司", "source": "parsed", "version_no": 1},
        {"field_name": "experience[0].description", "value": "带暑期培训班，批改作业", "source": "parsed", "version_no": 1},
        {"field_name": "experience[1].company", "value": "某科技公司", "source": "parsed", "version_no": 1},
        {"field_name": "experience[1].description", "value": "用 Python 与 FastAPI 开发后端接口", "source": "parsed", "version_no": 1},
        {"field_name": "skills[0]", "value": "Photoshop", "source": "parsed", "version_no": 1},
        {"field_name": "skills[1]", "value": "Python", "source": "parsed", "version_no": 1},
        {"field_name": "skills[2]", "value": "FastAPI", "source": "parsed", "version_no": 1},
        {"field_name": "honors[0]", "value": "奖学金", "source": "parsed", "version_no": 1},
        {"field_name": "unrecognized[0]", "value": "个人爱好广泛", "source": "unrecognized", "version_no": 1},
    ]


class TestPlanTailored:
    def test_reorders_by_jd_relevance(self):
        """相关条目/技能前移，索引同步重编号。"""
        plan = plan_tailored(_fields(), MATCH_META)
        assert plan.changed
        names = [f["field_name"] for f in plan.fields]
        # 经历：命中 2 项要求的科技公司实习前移到 [0]
        assert names.index("experience[0].company") < names.index("experience[1].company")
        idx_tech = names.index("experience[0].company")
        assert plan.fields[idx_tech]["value"] == "某科技公司"
        # 技能：Python / FastAPI 前置，Photoshop 后移
        skills = [f["value"] for f in plan.fields if f["field_name"].startswith("skills[")]
        assert skills == ["Python", "FastAPI", "Photoshop"]

    def test_values_never_change(self):
        """红线：只许换顺序，值多重集逐一守恒。"""
        before = _fields()
        plan = plan_tailored(before, MATCH_META)
        b = Counter(str(f["value"]) for f in before)
        a = Counter(str(f["value"]) for f in plan.fields)
        assert b == a

    def test_identity_sections_keep_order(self):
        """教育/荣誉/未识别内容/基本信息不参与重排（身份事实）。"""
        before = _fields()
        plan = plan_tailored(before, MATCH_META)
        for prefix in ("basic_info.", "education[0].", "honors[0]", "unrecognized[0]"):
            b = [f["field_name"] for f in before if f["field_name"].startswith(prefix)]
            a = [f["field_name"] for f in plan.fields if f["field_name"].startswith(prefix)]
            assert b == a

    def test_no_requirements_no_moves(self):
        """无 JD 要求（空匹配）时零移动。"""
        plan = plan_tailored(_fields(), {"matches": [], "gaps": []})
        assert not plan.changed
        assert plan.moves == []

    def test_already_tailored_no_moves(self):
        """顺序已贴合岗位时经历零移动（只重排仍需调整的技能）。"""
        # 直接构造"已贴合"态：科技公司实习已在 [0]，技能仍为 Photoshop/Python/FastAPI
        fields = [
            {"field_name": "basic_info.name", "value": "王五", "source": "parsed", "version_no": 1},
            {"field_name": "education[0].school", "value": "南京大学", "source": "parsed", "version_no": 1},
            {"field_name": "experience[0].company", "value": "某科技公司", "source": "parsed", "version_no": 1},
            {"field_name": "experience[0].description", "value": "用 Python 与 FastAPI 开发后端接口", "source": "parsed", "version_no": 1},
            {"field_name": "experience[1].company", "value": "某教育公司", "source": "parsed", "version_no": 1},
            {"field_name": "experience[1].description", "value": "带暑期培训班，批改作业", "source": "parsed", "version_no": 1},
            {"field_name": "skills[0]", "value": "Photoshop", "source": "parsed", "version_no": 1},
            {"field_name": "skills[1]", "value": "Python", "source": "parsed", "version_no": 1},
            {"field_name": "skills[2]", "value": "FastAPI", "source": "parsed", "version_no": 1},
        ]
        plan = plan_tailored(fields, MATCH_META)
        exp_moves = [m for m in plan.moves if m.field_name.startswith("experience")]
        assert exp_moves == [], "经历顺序已贴合，不应再移动"
        skill_values = [f["value"] for f in plan.fields if f["field_name"].startswith("skills[")]
        assert skill_values == ["Python", "FastAPI", "Photoshop"]

    def test_deterministic(self):
        """确定性：相同输入 → 相同计划（NFR-08）。"""
        a = plan_tailored(_fields(), MATCH_META)
        b = plan_tailored(_fields(), MATCH_META)
        assert [f["field_name"] for f in a.fields] == [f["field_name"] for f in b.fields]
        assert [(m.field_name, m.from_index, m.to_index) for m in a.moves] == [
            (m.field_name, m.from_index, m.to_index) for m in b.moves
        ]

    def test_word_boundary_no_false_hits(self):
        """词边界匹配：JD 要求 'Go' 不得命中 'Django'。"""
        fields = [
            {"field_name": "experience[0].company", "value": "A 公司", "source": "parsed", "version_no": 1},
            {"field_name": "experience[0].description", "value": "使用 Django 开发", "source": "parsed", "version_no": 1},
            {"field_name": "experience[1].company", "value": "B 公司", "source": "parsed", "version_no": 1},
            {"field_name": "experience[1].description", "value": "使用 Go 开发", "source": "parsed", "version_no": 1},
        ]
        meta = {"matches": [{"requirement": "Go", "kind": "skill", "verdict": "covered"}], "gaps": []}
        plan = plan_tailored(fields, meta)
        # 只有 Go 条目相关度 1，Django 条目 0 → Go 前移
        names = [f["field_name"] for f in plan.fields]
        assert names.index("experience[0].company") < names.index("experience[1].company")
        assert plan.fields[0]["value"] == "B 公司"


def _upload(client, text: str) -> str:
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["resume_id"]


def _prepare(client):
    """上传 → 提交 JD → 带 JD 诊断，返回 (resume_id, jd_id)。"""
    rid = _upload(client, RESUME_TXT)
    jd_resp = client.post(
        "/api/v1/job-descriptions",
        json={"title": "后端开发工程师", "raw_text": JD_TEXT},
    )
    jd_id = jd_resp.json()["data"]["jd_id"]
    diag = client.post("/api/v1/diagnoses", json={"resume_id": rid, "jd_id": jd_id})
    assert diag.status_code == 200
    return rid, jd_id


class TestTailorApi:
    def test_full_flow(self, client):
        """完整链路：定制生成 → 版本+1 → moves 合理 → draft.jd_id 记录岗位。"""
        rid, jd_id = _prepare(client)
        resp = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["changed"] is True
        assert data["jd_title"] == "后端开发工程师"
        assert data["current_version"] >= 2  # 首版 init + 定制版
        assert any(m["action"] == "promoted" for m in data["moves"])
        # 草稿确实记录了目标岗位
        draft = client.get(f"/api/v1/resumes/{rid}/draft").json()["data"]
        assert draft["jd_id"] == jd_id

    def test_tailor_without_match_diagnosis(self, client):
        """没有针对该 JD 的 match 诊断 → 6007（定制必须依据匹配结果）。"""
        rid = _upload(client, RESUME_TXT)
        jd_resp = client.post(
            "/api/v1/job-descriptions",
            json={"title": "后端开发工程师", "raw_text": JD_TEXT},
        )
        jd_id = jd_resp.json()["data"]["jd_id"]
        resp = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id})
        assert resp.status_code == 200
        assert resp.json()["code"] == 6007

    def test_tailor_jd_not_found(self, client):
        """JD 不存在 → 2004。"""
        rid = _upload(client, RESUME_TXT)
        resp = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": "no-such-jd"})
        assert resp.json()["code"] == 2004

    def test_tailor_resume_not_found(self, client):
        """简历不存在 → 2003。"""
        resp = client.post("/api/v1/tailors", json={"resume_id": "no-such", "jd_id": "no-such-jd"})
        assert resp.json()["code"] == 2003

    def test_repeat_tailor_no_empty_version(self, client):
        """重复定制：第二次无移动 → changed=False 且不产生新版本。"""
        rid, jd_id = _prepare(client)
        first = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id}).json()["data"]
        assert first["changed"] is True
        second = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id}).json()["data"]
        assert second["changed"] is False
        assert second["current_version"] == first["current_version"]
        assert second["moves"] == []

    def test_tailor_is_rollbackable(self, client):
        """定制可回滚：rollback 到首版（定制前），字段顺序恢复（NFR-10）。"""
        rid, jd_id = _prepare(client)
        tailored = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id}).json()["data"]
        assert tailored["changed"] is True
        after_skills = [
            f["value"]
            for f in client.get(f"/api/v1/drafts/{tailored['draft_id']}").json()["data"]["fields"]
            if f["field_name"].startswith("skills[")
        ]
        assert after_skills[0] != "Photoshop"  # 定制已生效

        # 期望值从解析结果取（草稿由它初始化，即"定制前"的真实顺序）
        structure = client.get(f"/api/v1/resumes/{rid}/structure").json()["data"]
        expected_skills = structure["structure"]["skills"]
        assert expected_skills[0] == "Photoshop"

        rollback = client.post(
            f"/api/v1/drafts/{tailored['draft_id']}/rollback",
            json={"revision_no": 1},  # 首版 = 定制前
        )
        assert rollback.status_code == 200
        after = client.get(f"/api/v1/drafts/{tailored['draft_id']}").json()["data"]
        restored_skills = [f["value"] for f in after["fields"] if f["field_name"].startswith("skills[")]
        assert restored_skills == expected_skills  # 逐字一致回到定制前

    def test_tailor_after_delete_returns_2003(self, client):
        """软删除后不可定制（NFR-05）。"""
        rid, jd_id = _prepare(client)
        client.delete(f"/api/v1/resumes/{rid}")
        resp = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id})
        assert resp.json()["code"] == 2003

    def test_tailor_reproducible(self, client):
        """同一状态两次定制（第二次无变化）+ 重置后再定制，计划一致（NFR-08）。"""
        rid, jd_id = _prepare(client)
        first = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id}).json()["data"]
        assert first["changed"] is True
        # 回滚到定制前，再次定制 → moves 应完全一致
        client.post(
            f"/api/v1/drafts/{first['draft_id']}/rollback",
            json={"revision_no": first["current_version"] - 1},
        )
        second = client.post("/api/v1/tailors", json={"resume_id": rid, "jd_id": jd_id}).json()["data"]
        assert second["changed"] is True
        assert [
            (m["field_name"], m["from_index"], m["to_index"], m["hits"]) for m in first["moves"]
        ] == [(m["field_name"], m["from_index"], m["to_index"], m["hits"]) for m in second["moves"]]
