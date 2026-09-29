"""用户自带模型接入测试（AIRewriteEngine + model_settings 契约）。

对应设计文档 4.5.7「可信性设计」在 AI 场景下的延伸，重点验证四条：
  1. AI 产出与规则引擎**受同一套事实守恒约束**——编造内容一律 rejected，
     违规文本绝不透出（这是本模块最重要的兜底）；
  2. 模型调用失败（超时 / 鉴权 / 服务端错误 / 返回不可解析 / 空内容）
     一律降级为 suggestion_only，复用既有 FR-12 路径，不新增错误码；
  3. **API Key 保密性**：不出现在 reason / model_version / 响应体 / 落库记录里；
  4. 不传 model_settings 时，行为与改造前完全一致（不破坏既有 278 项链路）。

网络全部用假 httpx.Client 拦截，不发真实请求。
"""
import io

import httpx
import pytest

from app.optimize.ai_engine import (
    AIRewriteEngine,
    _clean_model_output,
    build_engine,
    normalize_base_url,
)
from app.optimize.engine import RewriteRequest, fix_mixed_punctuation

SECRET_KEY = "sk-super-secret-key-987654"

# 只改标点的安全改写（事实守恒）
SAFE_TEXT = "负责订单服务接口开发，使用 Python 与 MySQL"
# 原文含"10 万"这一数字事实
ORIGINAL_WITH_NUMBER = "负责订单服务接口开发，日均支撑 10 万次调用"
# 把数字放大的编造改写（必须被拒绝）
FABRICATED_TEXT = "负责订单服务接口开发，日均支撑 500 万次调用"


# ---------- 假 HTTP 层 ----------


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("响应体不是 JSON")
        return self._payload


def _chat(content) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _FakeClient:
    """按脚本返回响应的假 httpx.Client，支持 with 语法。"""

    def __init__(self, handler):
        self._handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        return self._handler(url, headers, json)


def _patch_http(monkeypatch, handler) -> None:
    """把 httpx.Client 换成假实现（monkeypatch 负责还原）。"""
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: _FakeClient(handler))


def _engine(monkeypatch, handler) -> AIRewriteEngine:
    _patch_http(monkeypatch, handler)
    return build_engine("https://api.example.com", SECRET_KEY, "test-model")


def _echo_punct_fix(url, headers, json):
    """模拟一个"守规矩"的模型：只把原文里的英文标点转中文，不增不减任何内容。

    返回内容由请求里的原文决定——这样对任意字段都天然满足事实守恒，
    避免用固定文本把原文的事实删掉而误触 6002。
    """
    text = json["messages"][1]["content"]
    original = text.split("【简历原文】", 1)[1].strip()
    return _FakeResponse(200, _chat(fix_mixed_punctuation(original)))


def _req(text: str, category: str = "内容质量·描述不够具体") -> RewriteRequest:
    return RewriteRequest(
        issue={
            "issue_id": "iss-000001",
            "category": category,
            "problem": "描述缺少做法与结果",
            "suggestion": "补充具体做法",
        },
        field_name="experience[0].description",
        field_text=text,
    )


# ---------- 纯逻辑：地址归一化 ----------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1/chat/completions"),
        (
            "https://api.deepseek.com/v1/chat/completions",
            "https://api.deepseek.com/v1/chat/completions",
        ),
        ("http://localhost:11434", "http://localhost:11434/v1/chat/completions"),
        ("  https://api.example.com/  ", "https://api.example.com/v1/chat/completions"),
    ],
)
def test_normalize_base_url(given, expected):
    assert normalize_base_url(given) == expected


def test_build_engine_rejects_invalid_config():
    with pytest.raises(ValueError):
        build_engine("ftp://api.example.com", SECRET_KEY, "m")
    with pytest.raises(ValueError):
        build_engine("https://api.example.com", SECRET_KEY, "   ")
    with pytest.raises(ValueError):
        build_engine("", SECRET_KEY, "m")


def test_build_engine_metadata_hides_endpoint():
    engine = build_engine("https://api.example.com/v1", SECRET_KEY, "deepseek-chat")
    assert engine.version == "ai-deepseek-chat"
    assert engine.reproducible is False
    # 版本号用于追溯"这条改写是谁产出的"，不含端点与密钥
    assert "example.com" not in engine.version
    assert SECRET_KEY not in engine.version


# ---------- 纯逻辑：模型输出清洗 ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```\n改写后的文本\n```", "改写后的文本"),
        ("```text\n改写后的文本\n```", "改写后的文本"),
        ("改写后：优化过的文本", "优化过的文本"),
        ("修改后：优化过的文本", "优化过的文本"),
        ('"整体被引号包裹"', "整体被引号包裹"),
        ("  普通文本  ", "普通文本"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_clean_model_output(raw, expected):
    assert _clean_model_output(raw) == expected


def test_clean_model_output_keeps_inner_quotes():
    # 只有整体被包裹时才剥离，正文里的引号必须保留
    text = '他说"这个方案可行"，然后继续推进'
    assert _clean_model_output(text) == text


# ---------- 引擎：成功路径与事实守恒 ----------


def test_ai_engine_generates_and_passes_fact_check(monkeypatch):
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(200, _chat(SAFE_TEXT)))
    out = engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    assert out.status == "generated"
    assert out.after == SAFE_TEXT
    assert out.fact_check is not None and out.fact_check.passed
    assert out.model_version == "ai-test-model"
    # 相同输入不保证相同输出，必须如实标注（NFR-08 只约束确定性引擎）
    assert out.reproducible is False


def test_ai_engine_rejects_fabricated_number(monkeypatch):
    """模型放大业绩数字 → 基类事实守恒判 rejected，违规文本绝不透出。"""
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(200, _chat(FABRICATED_TEXT)))
    out = engine.rewrite(_req(ORIGINAL_WITH_NUMBER))

    assert out.status == "rejected"
    assert out.after == ""  # 关键：违规内容不出现在产出里
    assert out.fact_check.violated
    assert "拒绝" in out.reason


def test_ai_engine_rejects_fabricated_praise(monkeypatch):
    """模型添加"获得一致好评"这类评价性主张 → 同样被拒（KIND_CLAIM 参与守恒）。"""
    engine = _engine(
        monkeypatch,
        lambda *a: _FakeResponse(200, _chat("负责订单服务接口开发，获得一致好评")),
    )
    out = engine.rewrite(_req("负责订单服务接口开发"))

    assert out.status == "rejected"
    assert out.after == ""
    assert any(f["kind"] == "claim" for f in out.fact_check.added)


def test_ai_engine_strips_fence_before_fact_check(monkeypatch):
    """带代码围栏的返回先清洗再比对，不应因包装被误判。"""
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(200, _chat(f"```\n{SAFE_TEXT}\n```")))
    out = engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    assert out.status == "generated"
    assert out.after == SAFE_TEXT


# ---------- 引擎：失败一律降级，不新增错误码 ----------


@pytest.mark.parametrize(
    "name,handler,keyword",
    [
        ("超时", lambda *a: (_ for _ in ()).throw(httpx.TimeoutException("timeout")), "超时"),
        ("网络错误", lambda *a: (_ for _ in ()).throw(httpx.ConnectError("refused")), "网络失败"),
        ("鉴权失败", lambda *a: _FakeResponse(401, {}), "鉴权失败"),
        ("无权限", lambda *a: _FakeResponse(403, {}), "鉴权失败"),
        ("地址不存在", lambda *a: _FakeResponse(404, {}), "不存在"),
        ("限流", lambda *a: _FakeResponse(429, {}), "超限"),
        ("服务端错误", lambda *a: _FakeResponse(500, {"error": "boom"}), "错误状态"),
        ("非 JSON", lambda *a: _FakeResponse(200, None), "无法解析"),
        ("缺 choices", lambda *a: _FakeResponse(200, {"foo": 1}), "无法解析"),
        ("空内容", lambda *a: _FakeResponse(200, _chat("   ")), "未返回有效内容"),
        ("无改动", lambda *a: _FakeResponse(200, _chat("负责订单服务接口开发, 使用 Python 与 MySQL")), "未产生实际改动"),
    ],
)
def test_ai_engine_failures_degrade_to_suggestion(monkeypatch, name, handler, keyword):
    engine = _engine(monkeypatch, handler)
    out = engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    assert out.status == "suggestion_only", name
    assert out.after == "", name
    assert keyword in out.reason, name


def test_ai_engine_missing_model_name_degrades(monkeypatch):
    """直接构造引擎（绕过 build_engine 校验）时，缺模型名仍安全降级——纵深防御。"""
    _patch_http(monkeypatch, lambda *a: _FakeResponse(200, _chat(SAFE_TEXT)))
    engine = AIRewriteEngine(
        base_url="https://api.example.com", api_key=SECRET_KEY, model=""
    )
    out = engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    assert out.status == "suggestion_only"
    assert "模型名称" in out.reason


# ---------- 密钥保密性 ----------


def test_api_key_never_leaks_into_outcome(monkeypatch):
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(200, _chat(SAFE_TEXT)))
    out = engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    blob = str(out.to_dict())
    assert SECRET_KEY not in blob
    assert "api.example.com" not in blob


def test_api_key_not_in_failure_reason(monkeypatch):
    """失败说明只描述原因，不回显请求内容（响应体可能回显原文）。"""
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(400, {"error": "bad key sk-super-secret"}))
    out = engine.rewrite(_req("负责订单服务接口开发"))

    assert out.status == "suggestion_only"
    assert SECRET_KEY not in out.reason
    assert out.after == ""


def test_request_payload_contains_no_key(monkeypatch):
    """Key 只走 Authorization 头，不进请求体（请求体可能被日志记录）。"""
    captured = {}

    def handler(url, headers, json):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(200, _chat(SAFE_TEXT))

    engine = _engine(monkeypatch, handler)
    engine.rewrite(_req("负责订单服务接口开发, 使用 Python 与 MySQL"))

    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {SECRET_KEY}"
    assert SECRET_KEY not in str(captured["json"])


# ---------- 连接自检 ----------


def test_ping_success(monkeypatch):
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(200, _chat("hi")))
    ok, detail = engine.ping()
    assert ok is True
    assert "test-model" in detail
    assert SECRET_KEY not in detail


@pytest.mark.parametrize(
    "status,expected",
    [(401, "鉴权失败"), (403, "鉴权失败"), (404, "不存在"), (500, "错误状态")],
)
def test_ping_reports_failure_reason(monkeypatch, status, expected):
    engine = _engine(monkeypatch, lambda *a: _FakeResponse(status, {}))
    ok, detail = engine.ping()
    assert ok is False
    assert expected in detail
    assert SECRET_KEY not in detail


def test_ping_timeout(monkeypatch):
    engine = _engine(monkeypatch, lambda *a: (_ for _ in ()).throw(httpx.TimeoutException("t")))
    ok, detail = engine.ping()
    assert ok is False
    assert "超时" in detail


# ---------- API 层 ----------

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


def _upload(client, content: str) -> str:
    resp = client.post(
        "/api/v1/resumes",
        files={"file": ("r.txt", io.BytesIO(content.encode("utf-8")), "text/plain")},
    )
    assert resp.status_code == 200
    return resp.json()["data"]["resume_id"]


def _diagnose(client, resume_id: str) -> dict:
    resp = client.post("/api/v1/diagnoses", json={"resume_id": resume_id})
    assert resp.status_code == 200
    return resp.json()["data"]


def _pick_issue(client, resume_id: str, category_contains: str) -> dict:
    report = client.get(f"/api/v1/reports/{resume_id}").json()["data"]
    for issue in report["issues"]:
        if category_contains in issue["category"]:
            return issue
    pytest.skip(f"该简历未产生含「{category_contains}」的问题项")


def test_api_rewrite_with_model_settings_uses_ai(client, monkeypatch):
    """传入 model_settings → 本次请求改用 AI 引擎。"""
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    _patch_http(monkeypatch, _echo_punct_fix)
    resp = client.post(
        "/api/v1/rewrites",
        json={
            "resume_id": resume_id,
            "issue_id": issue["issue_id"],
            "model_settings": {
                "base_url": "https://api.example.com",
                "api_key": SECRET_KEY,
                "model": "test-model",
            },
        },
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["code"] == 0
    data = body["data"]
    assert data["model_version"] == "ai-test-model"
    assert data["reproducible"] is False
    # 该字段原文含英文逗号，模型只做标点转换 → 正常产出且事实守恒
    assert data["status"] == "generated"
    assert data["fact_check"]["passed"] is True
    assert SECRET_KEY not in str(data)


def test_api_rewrite_without_model_settings_still_rule_engine(client):
    """不传 model_settings → 仍是规则引擎，行为与改造前一致（不破坏既有链路）。"""
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    resp = client.post(
        "/api/v1/rewrites",
        json={"resume_id": resume_id, "issue_id": issue["issue_id"]},
    )
    data = resp.json()["data"]
    assert data["model_version"] == "rule-rewrite-1.0.0"
    assert data["reproducible"] is True


def test_api_rewrite_ai_fabrication_rejected_with_6002(client, monkeypatch):
    """AI 编造内容 → 6002，且违规文本不在响应体里（设计文档 7.3 负面测试要点）。"""
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    _patch_http(monkeypatch, lambda *a: _FakeResponse(200, _chat(FABRICATED_TEXT)))
    resp = client.post(
        "/api/v1/rewrites",
        json={
            "resume_id": resume_id,
            "issue_id": issue["issue_id"],
            "model_settings": {
                "base_url": "https://api.example.com",
                "api_key": SECRET_KEY,
                "model": "test-model",
            },
        },
    )
    body = resp.json()
    assert body["code"] == 6002
    assert FABRICATED_TEXT not in str(body)
    assert SECRET_KEY not in str(body)


def test_api_rewrite_ai_timeout_degrades_not_error(client, monkeypatch):
    """模型超时不是接口错误：返回 suggestion_only，让用户手动处理。"""
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    _patch_http(monkeypatch, lambda *a: (_ for _ in ()).throw(httpx.TimeoutException("t")))
    resp = client.post(
        "/api/v1/rewrites",
        json={
            "resume_id": resume_id,
            "issue_id": issue["issue_id"],
            "model_settings": {
                "base_url": "https://api.example.com",
                "api_key": SECRET_KEY,
                "model": "test-model",
            },
        },
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "suggestion_only"
    assert "超时" in body["data"]["reason"]


@pytest.mark.parametrize(
    "bad",
    [
        # 三种都能穿过 Pydantic 的 min_length，但构不成可用端点 → 由服务层判 6008
        {"base_url": "ftp://api.example.com", "api_key": "k", "model": "m"},
        {"base_url": "example.com", "api_key": "k", "model": "m"},
        {"base_url": "https://api.example.com", "api_key": "k", "model": "  "},
    ],
)
def test_api_rewrite_invalid_model_settings_6008(client, bad):
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    resp = client.post(
        "/api/v1/rewrites",
        json={"resume_id": resume_id, "issue_id": issue["issue_id"], "model_settings": bad},
    )
    body = resp.json()
    assert body["code"] == 6008
    assert SECRET_KEY not in str(body)


def test_api_model_settings_test_success(client, monkeypatch):
    _patch_http(monkeypatch, lambda *a: _FakeResponse(200, _chat("hi")))
    resp = client.post(
        "/api/v1/model-settings/test",
        json={
            "base_url": "https://api.example.com",
            "api_key": SECRET_KEY,
            "model": "test-model",
        },
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["available"] is True
    assert SECRET_KEY not in str(body)


def test_api_model_settings_test_auth_failure(client, monkeypatch):
    _patch_http(monkeypatch, lambda *a: _FakeResponse(401, {}))
    resp = client.post(
        "/api/v1/model-settings/test",
        json={
            "base_url": "https://api.example.com",
            "api_key": SECRET_KEY,
            "model": "test-model",
        },
    )
    body = resp.json()
    assert body["code"] == 6008
    assert "鉴权" in body["message"]
    assert SECRET_KEY not in str(body)


def test_api_model_settings_test_invalid_config(client):
    resp = client.post(
        "/api/v1/model-settings/test",
        json={"base_url": "not-a-url", "api_key": "k", "model": "m"},
    )
    assert resp.json()["code"] == 6008


def test_api_rewrite_partial_model_settings_rejected_by_schema(client):
    """缺字段由 Pydantic 拦截：不会走到"以为配了 AI 其实用了规则引擎"的歧义状态。"""
    resume_id = _upload(client, RESUME_WITH_ISSUES)
    _diagnose(client, resume_id)
    issue = _pick_issue(client, resume_id, "标点")

    resp = client.post(
        "/api/v1/rewrites",
        json={
            "resume_id": resume_id,
            "issue_id": issue["issue_id"],
            "model_settings": {"base_url": "https://api.example.com"},
        },
    )
    assert resp.status_code == 422
