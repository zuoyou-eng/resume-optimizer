"""ORM 模型：与《系统设计文档》第 6 章数据模型对齐（初始版本实现 Resume / ParseResult）。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, JsonType


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DraftStatus:
    """草稿状态（设计文档 4.5.5）。"""

    DRAFT = "draft"
    EXPORTED = "exported"
    ARCHIVED = "archived"


class RiskLevel:
    """改写风险等级（O-07 分界线，判定只能在服务端做）。"""

    AUTO_SAFE = "auto_safe"
    NEEDS_REVIEW = "needs_review"


class Resume(Base):
    """简历文件实体（设计文档 6.2：file_hash 去重，deleted_at 支撑软删除/NFR-05）。"""

    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    original_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(Integer)
    # uploaded / parsed / parse_failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    parse_results: Mapped[list["ParseResult"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )
    # 诊断与报告同为简历衍生数据，删除简历时必须级联清除（NFR-05 隐私要求）
    diagnoses: Mapped[list["Diagnosis"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )
    report: Mapped["Report | None"] = relationship(
        back_populates="resume", cascade="all, delete-orphan", uselist=False
    )
    # 草稿与版本快照同属简历衍生数据，删除简历时级联清除（设计文档 6.2 隐私关联）
    drafts: Mapped[list["ResumeDraft"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ParseResult(Base):
    """结构化解析结果与解析轨迹（设计文档 4.3：trace 让判定过程可追溯）。"""

    __tablename__ = "parse_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id"), index=True
    )
    structure: Mapped[dict] = mapped_column(JsonType)  # 结构化简历（JSONB）
    trace: Mapped[list] = mapped_column(JsonType)      # 解析轨迹（JSONB）
    unrecognized: Mapped[list] = mapped_column(JsonType)  # 未识别内容（FR-03：严禁静默丢失）
    rule_version: Mapped[str] = mapped_column(String(20))
    parse_status: Mapped[str] = mapped_column(String(20))  # success / failed
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    resume: Mapped[Resume] = relationship(back_populates="parse_results")


class JobDescription(Base):
    """岗位描述及其提取的关键要求（设计文档 6.2；FR-08 的比对基准）。"""

    __tablename__ = "job_descriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), default="")
    raw_text: Mapped[str] = mapped_column(String(20000))
    extracted_keys: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Diagnosis(Base):
    """一次诊断记录（设计文档 6.2：dimension / score / status / meta）。

    dimension 取值：norm（FR-04 基础规范）/ content（FR-05 内容质量）/
    machine（FR-06 ATS 适配）/ match（FR-08 岗位匹配）。
    meta 中记录 rule_version / model_version / elapsed_ms / reproducible，
    直接对应 NFR-08「相同输入 → 相同结论」的可断言要求。
    """

    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id"), index=True
    )
    jd_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_descriptions.id"), nullable=True
    )
    dimension: Mapped[str] = mapped_column(String(20))
    module_name: Mapped[str] = mapped_column(String(50))
    score: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="success")  # success / failed
    # 确定性内容指纹：同输入 → 同指纹（NFR-08 可复现的落库依据）。
    # 主键必须是 UUID——同一份简历可多次诊断（优化前后对比依赖历史记录），
    # 若用确定性 ID 作主键，第二次诊断就会撞 UNIQUE 约束。
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    resume: Mapped[Resume] = relationship(back_populates="diagnoses")
    issues: Mapped[list["Issue"]] = relationship(
        back_populates="diagnosis", cascade="all, delete-orphan"
    )


class Issue(Base):
    """问题项（设计文档 4.2 统一诊断结果模型）。

    location 为 JSON：{field, snippet, offset}——每条结论必须可定位（原则三）。
    evidence 记录判定依据，confidence 表达非确定性结论的可信程度，
    二者共同支撑"测试可验证判定过程而非仅验证结论"。
    """

    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    diagnosis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("diagnoses.id"), index=True
    )
    # 问题业务编号（确定性，同输入同编号）；主键为 UUID，
    # 唯一性约束为 (diagnosis_id, issue_code)——同一诊断内不重复，跨诊断可复现
    issue_code: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # critical/major/minor/info
    category: Mapped[str] = mapped_column(String(50))
    location: Mapped[dict] = mapped_column(JsonType, default=dict)
    problem: Mapped[str] = mapped_column(String(1000))
    suggestion: Mapped[str] = mapped_column(String(1000))
    evidence: Mapped[str] = mapped_column(String(1000))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (UniqueConstraint("diagnosis_id", "issue_code"),)

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="issues")


class Report(Base):
    """综合报告（设计文档 6.2 / FR-10 综合健康分 / FR-11 问题清单）。

    与简历一对一：每次诊断后刷新，保证 GET /api/v1/reports/{resume_id}
    拿到的始终是当前最新结论；issue_summary 保存按优先级排序后的问题清单。
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id"), unique=True, index=True
    )
    total_score: Mapped[int] = mapped_column(Integer)
    dimension_scores: Mapped[dict] = mapped_column(JsonType, default=dict)
    issue_summary: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    resume: Mapped[Resume] = relationship(back_populates="report")


class ResumeDraft(Base):
    """结构化简历草稿（O-04，设计文档 4.5.5）。

    定位是**字段级文本编辑**，不是排版编辑器：只维护每个字段的文本内容，
    不涉及字体、分栏、模板。fields 为 JSONB：
      [{field_name, value, source, version_no}]
    source 取值：parsed（原解析）| rewritten（改写采纳）| manual（手工编辑）
    """

    __tablename__ = "resume_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id"), index=True
    )
    jd_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("job_descriptions.id"), nullable=True
    )
    fields: Mapped[list] = mapped_column(JsonType, default=list)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    # draft | exported | archived
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    resume: Mapped[Resume] = relationship(back_populates="drafts")
    revisions: Mapped[list["Revision"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class Revision(Base):
    """版本快照（O-03 / NFR-10，设计文档 4.5.5）。

    采用**全量快照 + 版本指针**而非反向操作日志：撤销后"逐字一致"由此
    结构性成立，测试只需验证"快照内容确实被完整保存"，无需穷举操作组合。
    **用设计消除测试难度，而不是用测试去追设计漏洞。**
    """

    __tablename__ = "revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_drafts.id"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[list] = mapped_column(JsonType, default=list)  # 完整字段快照
    # apply | manual_edit | batch_apply | rollback
    operation: Mapped[str] = mapped_column(String(20))
    rewrite_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (UniqueConstraint("draft_id", "revision_no"),)

    draft: Mapped[ResumeDraft] = relationship(back_populates="revisions")


class RewriteResult(Base):
    """改写结果（O-01/O-02，设计文档 4.5.2）。

    issue_id 为**必填外键**——从数据层面保证"没有诊断结论就没有改写"，
    这是设计约束而非仅靠代码纪律（设计文档 6.2 原文）。
    """

    __tablename__ = "rewrite_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id"), index=True
    )
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id"), index=True
    )
    target_field: Mapped[str] = mapped_column(String(100))
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    before: Mapped[str] = mapped_column(String(2000))
    after: Mapped[str] = mapped_column(String(2000))
    # generated | suggestion_only | rejected
    status: Mapped[str] = mapped_column(String(20))
    change_points: Mapped[list] = mapped_column(JsonType, default=list)
    fact_check: Mapped[dict] = mapped_column(JsonType, default=dict)
    # auto_safe | needs_review（O-07 分界线，判定只在服务端做）
    risk_level: Mapped[str] = mapped_column(String(20))
    risk_reasons: Mapped[list] = mapped_column(JsonType, default=list)
    model_version: Mapped[str] = mapped_column(String(50))
    reproducible: Mapped[bool] = mapped_column(Boolean, default=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
