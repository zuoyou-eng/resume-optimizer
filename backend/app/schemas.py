"""Pydantic 数据契约：请求/响应结构强约束（设计文档 7.2 统一响应格式）。"""
from typing import Any
from pydantic import BaseModel, Field

from app.errors import trace_id_var


# ---------- 统一响应格式（设计文档 7.2） ----------

class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None
    trace_id: str


def ok(data: Any = None, message: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, message=message, data=data, trace_id=trace_id_var.get())


def fail(code: int, message: str) -> ApiResponse:
    return ApiResponse(code=code, message=message, data=None, trace_id=trace_id_var.get())


# ---------- 结构化简历模型（FR-02） ----------

class BasicInfo(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)


class EducationItem(BaseModel):
    school: str | None = None
    major: str | None = None
    degree: str | None = None
    period: str | None = None
    description: str | None = None


class ExperienceItem(BaseModel):
    company: str | None = None
    role: str | None = None
    period: str | None = None
    description: str | None = None


class ProjectItem(BaseModel):
    name: str | None = None
    role: str | None = None
    period: str | None = None
    description: str | None = None


class StructuredResume(BaseModel):
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    honors: list[str] = Field(default_factory=list)


# ---------- 解析轨迹（设计文档 4.3：记录"从哪里、用什么规则读到的"） ----------

class TraceItem(BaseModel):
    field: str                 # 字段名，如 basic_info.email / experience[0].description
    extracted: str             # 提取到的值
    source_region: str         # 来源区域（原文片段，截断展示）
    rule_applied: str          # 命中的提取规则
    verdict: str               # parsed（成功提取）


class UnrecognizedBlock(BaseModel):
    """无法归入任何结构化字段的原文内容（FR-03：必须显式提示，严禁静默丢失）。"""

    text: str
    reason: str = "无法归入已知字段"


# ---------- 接口输出模型 ----------

class ResumeMetaOut(BaseModel):
    id: str
    original_name: str
    file_type: str
    file_size: int
    status: str
    created_at: str


class ParseResultOut(BaseModel):
    resume_id: str
    parse_status: str
    rule_version: str
    structure: StructuredResume
    trace: list[TraceItem]
    unrecognized: list[UnrecognizedBlock]
    created_at: str


# ---------- 诊断（设计文档 7.1 接口 #3/#4/#5/#6） ----------

class DiagnoseRequest(BaseModel):
    """发起诊断：dimensions 缺省为全部三个"简历质量"维度（norm/content/machine）。"""

    resume_id: str = Field(..., min_length=1)
    dimensions: list[str] | None = None
    jd_id: str | None = None      # 传了才会执行岗位匹配维度（FR-08）


class JdSubmitRequest(BaseModel):
    """提交岗位描述（FR-08）：服务端提取关键要求并落库。

    长度下限交由业务层判定（返回 2005），不用 schema 的 min_length——
    否则过短的 JD 会先被 pydantic 拦成 422，错误码表就失去了对调用方的意义。
    """

    title: str = ""
    raw_text: str = Field(..., max_length=20000)


# ---------- 优化模块（设计文档 7.1 接口 #9-#18） ----------

class ModelSettings(BaseModel):
    """用户自带的模型配置（随请求一次性传入）。

    服务端**不落库、不记日志**：仅用于本次请求构建引擎实例，用完即弃。
    三者要么全部提供、要么全部不提供——缺任何一项都无法完成调用。

    字段名刻意不用 `model_config`：那是 Pydantic v2 的保留配置名。
    这里只做最基本的非空校验。地址是否可达、Key 是否有效，由
    `POST /model-settings/test` 明确反馈，不把"配错了"混进改写结果里。
    """

    base_url: str = Field(..., min_length=1, description="OpenAI 兼容接口地址")
    api_key: str = Field(..., min_length=1, description="API Key")
    model: str = Field(..., min_length=1, description="模型名称")


class GenerateRewriteRequest(BaseModel):
    """基于某条问题项发起改写（O-01）。

    不传 model_settings → 用确定性规则引擎（默认，产物恒为 auto_safe）；
    传入 model_settings → 本次请求改用用户自带模型（产物通常为 needs_review，
    需逐条人工确认）。风险分级与事实守恒在服务端强制，前端不可信。
    """

    resume_id: str = Field(..., min_length=1)
    issue_id: str = Field(..., min_length=1)
    model_settings: ModelSettings | None = None


class BatchApplyRequest(BaseModel):
    """批量应用确定性修正（O-06）。

    服务端只接受 auto_safe 项；传入 needs_review 一律返回 6003——
    风险分级判定只能在服务端做，前端不可信（设计文档 4.5.4 硬约束 2）。
    """

    rewrite_ids: list[str] = Field(..., min_length=1)


class ManualEditRequest(BaseModel):
    """手工编辑草稿字段（O-04）：同样产生一个新版本。"""

    field_name: str = Field(..., min_length=1)
    value: str


class RollbackRequest(BaseModel):
    """回滚到指定版本（O-03 / NFR-10）。"""

    revision_no: int = Field(..., ge=1)


class TailorRequest(BaseModel):
    """生成面向某岗位的定制草稿版本（O-08，只做取舍与重组）。"""

    resume_id: str = Field(..., min_length=1)
    jd_id: str = Field(..., min_length=1)


# ---------- 亮点挖掘（FR-09，V1.2 弹性项） ----------

class HighlightFieldRequest(BaseModel):
    """追问 / 合成请求：定位到某个经历描述字段。"""

    resume_id: str = Field(..., min_length=1)
    field_name: str = Field(..., min_length=1)


class HighlightComposeRequest(BaseModel):
    """合成预览请求：answers 为 {层名: 用户回答}，可缺层（跳过）。"""

    resume_id: str = Field(..., min_length=1)
    field_name: str = Field(..., min_length=1)
    answers: dict[str, str] = Field(default_factory=dict)


class HighlightConfirmRequest(BaseModel):
    """确认写入请求（FR-09：由用户确认后才写入）。

    after_text 由前端原样回传合成结果；服务端重新做事实守恒复核，
    不信任何前端中间状态（NFR-09）。
    """

    resume_id: str = Field(..., min_length=1)
    field_name: str = Field(..., min_length=1)
    after_text: str = Field(..., min_length=1)
    answers: dict[str, str] = Field(default_factory=dict)
