"""优化业务服务：改写 → 应用 → 版本 → 导出复检 → 对比（设计文档 4.5 / 5.2）。

分层边界（设计文档 4.1）：本层只做编排与持久化，**不含任何改写规则与判定逻辑**——
规则在 app/optimize/ 下的引擎与分级器里，因此可脱离服务单独测试。

两条必须在服务端强制、绝不能交给前端的约束：
  1. 风险分级判定（O-07）：批量应用只接受 auto_safe，传入 needs_review 一律 6003；
  2. 事实守恒校验（NFR-09）：由引擎基类统一执行，任何引擎都无法绕过。
"""
import copy
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.diagnosis.models import DIM_MACHINE
from app.diagnosis.runner import DIM_CONTENT, DIM_NORM, build_report, run_diagnosis
from app.errors import BizError, ErrorCode
from app.models import (
    Diagnosis,
    DraftStatus,
    Issue,
    ParseResult,
    Resume,
    ResumeDraft,
    Revision,
    RewriteResult,
)
from app.optimize.ai_engine import (
    DEFAULT_TIMEOUT_SECONDS,
    AIRewriteEngine,
    build_engine,
)
from app.optimize.draft_fields import fields_to_lines, structure_to_fields
from app.optimize.engine import (
    STATUS_GENERATED,
    RewriteEngine,
    RewriteRequest,
    RuleRewriteEngine,
)
from app.parser.structurer import structure_document
from app.services.storage import UPLOAD_DIR
from app.diagnosis.runner import DIM_CONTENT, DIM_NORM

PARSE_RULE_VERSION = "rule-1.0.0"

# 版本保留上限（设计文档 4.5.5：建议 N=20，保留首版 + 最近版本 + 导出前版本）
MAX_REVISIONS = 20

# 参与内容 diff 的操作
_CONTENT_OPS = {"apply", "batch_apply", "manual_edit", "rollback", "highlight"}

# Word 导出时加粗的章节标题
_DOCX_HEADINGS = {"教育背景", "实习经历", "项目经历", "专业技能", "荣誉奖项"}


class RewriteService:
    def __init__(self, db: Session, engine: RewriteEngine | None = None):
        self.db = db
        self.engine = engine or RuleRewriteEngine()

    # ---------- 内部：简历 / 草稿 ----------
    def _get_resume(self, resume_id: str) -> Resume:
        resume = self.db.get(Resume, resume_id)
        if resume is None or resume.deleted_at is not None:
            raise BizError(ErrorCode.RESUME_NOT_FOUND)
        return resume

    def _get_draft(self, draft_id: str) -> ResumeDraft:
        draft = self.db.get(ResumeDraft, draft_id)
        if draft is None:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "草稿不存在")
        return draft

    def _get_or_create_draft(self, resume_id: str, jd_id: str | None = None) -> ResumeDraft:
        """取该简历的草稿；没有则从解析结果初始化（O-04：为应用提供落点）。"""
        draft = self.db.execute(
            select(ResumeDraft)
            .where(ResumeDraft.resume_id == resume_id)
            .order_by(ResumeDraft.created_at.desc())
        ).scalars().first()
        if draft is not None:
            return draft

        parse = self.db.execute(
            select(ParseResult)
            .where(ParseResult.resume_id == resume_id)
            .order_by(ParseResult.created_at.desc())
        ).scalars().first()
        if parse is None:
            raise BizError(ErrorCode.PARSE_FAILED, "该简历尚未完成解析，无法创建草稿")

        # 未识别内容一并进草稿（FR-03）：诊断会针对它报问题项，
        # 草稿里没有对应字段的话，用户点改写只会拿到"字段不存在"的死胡同。
        fields = structure_to_fields(parse.structure or {}, parse.unrecognized or [])
        draft = ResumeDraft(
            resume_id=resume_id,
            jd_id=jd_id,
            fields=fields,
            current_version=1,
            status=DraftStatus.DRAFT,
        )
        self.db.add(draft)
        self.db.flush()
        # 首版快照：撤销链的起点
        self.db.add(
            Revision(
                draft_id=draft.id,
                revision_no=1,
                snapshot=copy.deepcopy(fields),
                operation="init",
            )
        )
        self.db.flush()
        return draft

    def _dominant_date_format(self, draft: ResumeDraft) -> str:
        """统计草稿中最常见的日期写法，作为格式统一的 target。"""
        counts = {"dot": 0, "slash": 0, "dash": 0, "cn": 0}
        for f in draft.fields or []:
            value = f.get("value") or ""
            if "." in value and any(ch.isdigit() for ch in value):
                counts["dot"] += 1
            elif "/" in value:
                counts["slash"] += 1
            elif "-" in value:
                counts["dash"] += 1
            elif "年" in value:
                counts["cn"] += 1
        best = max(counts, key=lambda k: counts[k])
        return best if counts[best] else "dot"

    # ---------- O-01 单条建议改写 ----------
    def _build_ai_engine(self, model_config) -> AIRewriteEngine:
        """按用户配置构建本次请求专用的 AI 引擎。

        配置**不落库**：引擎实例随请求结束即丢弃，API Key 不会进入任何表、
        日志或错误信息。这里只校验"配置本身是否成立"（6008）；
        地址是否可达、Key 是否有效由模型调用时的降级路径或连接自检反馈。
        """
        try:
            return build_engine(
                base_url=getattr(model_config, "base_url", "") or "",
                api_key=getattr(model_config, "api_key", "") or "",
                model=getattr(model_config, "model", "") or "",
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        except ValueError as exc:
            raise BizError(ErrorCode.MODEL_CONFIG_INVALID, str(exc)) from exc

    def generate(self, resume_id: str, issue_id: str, model_config=None) -> dict:
        self._get_resume(resume_id)
        # 按业务编号 + 简历联合查询：对外契约用的是确定性的 issue_code（可复现、可断言），
        # 不暴露数据库主键；联合 resume_id 保证不会串到别的简历上。
        issue = (
            self.db.execute(
                select(Issue)
                .join(Diagnosis, Issue.diagnosis_id == Diagnosis.id)
                .where(Issue.issue_code == issue_id, Diagnosis.resume_id == resume_id)
            )
            .scalars()
            .first()
        )
        if issue is None:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "问题项不存在或不属于该简历")

        diagnosis = self.db.get(Diagnosis, issue.diagnosis_id)
        draft = self._get_or_create_draft(resume_id, diagnosis.jd_id if diagnosis else None)

        # 改写范围锁定在该问题对应的字段内（设计文档 4.5.1 第 ① 步）
        field_name = (issue.location or {}).get("field") or ""
        field_text = ""
        for f in draft.fields or []:
            if f.get("field_name") == field_name:
                field_text = f.get("value") or ""
                break
        if not field_text:
            raise BizError(
                ErrorCode.REWRITE_TARGET_NOT_FOUND,
                f"目标字段 {field_name or '(未知)'} 在草稿中不存在或为空",
            )

        # 传入模型配置则本次请求改用用户自带模型，否则用默认规则引擎。
        # 事实守恒与风险分级由引擎基类统一执行，换引擎不影响这两条硬约束。
        engine = self._build_ai_engine(model_config) if model_config else self.engine

        outcome = engine.rewrite(
            RewriteRequest(
                issue={
                    "issue_id": issue.id,
                    "category": issue.category,
                    "problem": issue.problem,
                    "suggestion": issue.suggestion,
                    "location": issue.location,
                },
                field_name=field_name,
                field_text=field_text,
                dominant_date_format=self._dominant_date_format(draft),
            )
        )

        # 事实校验失败 → 6002，且**违规内容绝不落库**（设计文档 7.3 负面测试要点）
        if outcome.status == "rejected":
            raise BizError(ErrorCode.REWRITE_FACT_CHECK_FAILED, outcome.reason)

        record = RewriteResult(
            issue_id=issue.id,
            resume_id=resume_id,
            target_field=field_name,
            segment_index=0,
            before=outcome.before,
            after=outcome.after,
            status=outcome.status,
            change_points=[c.to_dict() for c in outcome.change_points],
            fact_check=outcome.fact_check.to_dict() if outcome.fact_check else {},
            risk_level=outcome.risk_level or "",
            risk_reasons=(outcome.risk.reasons if outcome.risk else []),
            model_version=outcome.model_version,
            reproducible=outcome.reproducible,
            applied=False,
        )
        self.db.add(record)
        self.db.flush()
        self.db.commit()

        return {
            "rewrite_id": record.id,
            "issue_id": record.issue_id,
            "draft_id": draft.id,
            "target_field": record.target_field,
            "status": record.status,
            "risk_level": record.risk_level,
            "before": record.before,
            "after": record.after,
            "change_points": record.change_points,
            "fact_check": record.fact_check,
            "risk_reasons": record.risk_reasons,
            "model_version": record.model_version,
            "reproducible": record.reproducible,
            "reason": outcome.reason,
        }

    # ---------- O-02 查询改写结果（含改动点与事实比对报告） ----------
    def get_rewrite(self, rewrite_id: str) -> dict:
        record = self.db.get(RewriteResult, rewrite_id)
        if record is None:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "改写记录不存在")
        return {
            "rewrite_id": record.id,
            "issue_id": record.issue_id,
            "resume_id": record.resume_id,
            "target_field": record.target_field,
            "status": record.status,
            "risk_level": record.risk_level,
            "before": record.before,
            "after": record.after,
            "change_points": record.change_points or [],
            "fact_check": record.fact_check or {},
            "risk_reasons": record.risk_reasons or [],
            "model_version": record.model_version,
            "reproducible": record.reproducible,
            "applied": record.applied,
            "created_at": record.created_at.isoformat(),
        }

    # ---------- O-03 应用单条改写 ----------
    def apply(self, rewrite_id: str) -> dict:
        record = self.db.get(RewriteResult, rewrite_id)
        if record is None:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "改写记录不存在")
        if record.status != STATUS_GENERATED or not record.after:
            raise BizError(
                ErrorCode.REWRITE_TARGET_NOT_FOUND,
                "该改写未产出可应用的文本（可能已被拒绝或仅为建议）",
            )
        if record.applied:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "该改写已应用过")

        draft = self._get_or_create_draft(record.resume_id)
        self._set_field(draft, record.target_field, record.after, source="rewritten")
        self._snapshot(draft, operation="apply", rewrite_id=record.id)

        record.applied = True
        self.db.commit()
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "applied_field": record.target_field,
            "value": record.after,
        }

    # ---------- O-06 / O-07 批量应用确定性修正 ----------
    def batch_apply(self, draft_id: str, rewrite_ids: list[str]) -> dict:
        draft = self._get_draft(draft_id)
        if not rewrite_ids:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "未指定要应用的改写")

        records = []
        for rid in rewrite_ids:
            record = self.db.get(RewriteResult, rid)
            if record is None:
                raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, f"改写 {rid} 不存在")
            if record.resume_id != draft.resume_id:
                raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "改写不属于该草稿")
            # 服务端强校验：needs_review 一律拒绝（前端不可信，O-07 硬约束 2）
            if record.status != STATUS_GENERATED or not record.after:
                raise BizError(
                    ErrorCode.REWRITE_TARGET_NOT_FOUND,
                    f"改写 {rid} 未产出可应用的文本",
                )
            if record.risk_level != "auto_safe":
                raise BizError(
                    ErrorCode.REWRITE_NOT_AUTO_SAFE,
                    f"改写 {rid} 风险等级为 {record.risk_level}，必须逐条人工确认后才能应用",
                )
            if record.applied:
                continue
            records.append(record)

        applied_fields: list[str] = []
        for record in records:
            self._set_field(draft, record.target_field, record.after, source="rewritten")
            record.applied = True
            applied_fields.append(record.target_field)

        if records:
            # 批量应用只产生一个版本（一次操作 = 一个版本，便于整体撤销）
            self._snapshot(draft, operation="batch_apply", rewrite_id=records[0].id)

        self.db.commit()
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "applied_count": len(records),
            "applied_fields": applied_fields,
        }

    # ---------- O-04 手工编辑字段 ----------
    def manual_edit(self, draft_id: str, field_name: str, value: str) -> dict:
        draft = self._get_draft(draft_id)
        self._set_field(draft, field_name, value, source="manual")
        self._snapshot(draft, operation="manual_edit")
        self.db.commit()
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "field": field_name,
            "value": value,
        }

    # ---------- O-03 撤销 / 回滚 ----------
    def rollback(self, draft_id: str, revision_no: int) -> dict:
        draft = self._get_draft(draft_id)
        target = self.db.execute(
            select(Revision).where(
                Revision.draft_id == draft.id, Revision.revision_no == revision_no
            )
        ).scalars().first()
        if target is None:
            raise BizError(
                ErrorCode.REVISION_NOT_FOUND,
                f"版本 {revision_no} 不存在或已被清理",
            )

        # 全量快照回退：直接把指针指向目标版本的完整内容。
        # "撤销后逐字一致"由此结构性成立，无需穷举操作组合验证。
        draft.fields = copy.deepcopy(target.snapshot)
        next_no = self._next_revision_no(draft.id)
        self.db.add(
            Revision(
                draft_id=draft.id,
                revision_no=next_no,
                snapshot=copy.deepcopy(target.snapshot),
                operation="rollback",
            )
        )
        draft.current_version = next_no
        self._prune_revisions(draft.id)
        self.db.commit()
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "rolled_back_to": revision_no,
        }

    # ---------- 草稿查询 ----------
    def get_draft(self, draft_id: str) -> dict:
        draft = self._get_draft(draft_id)
        return self._draft_payload(draft)

    def get_draft_by_resume(self, resume_id: str) -> dict:
        """按简历取草稿（前端草稿工作台入口）。没有草稿时返回空，不报错。"""
        self._get_resume(resume_id)
        draft = self.db.execute(
            select(ResumeDraft)
            .where(ResumeDraft.resume_id == resume_id)
            .order_by(ResumeDraft.created_at.desc())
        ).scalars().first()
        if draft is None:
            return {"draft_id": None, "resume_id": resume_id, "fields": []}
        return self._draft_payload(draft)

    def list_revisions(self, draft_id: str) -> dict:
        draft = self._get_draft(draft_id)
        revisions = (
            self.db.execute(
                select(Revision)
                .where(Revision.draft_id == draft.id)
                .order_by(Revision.revision_no.desc())
            )
            .scalars()
            .all()
        )
        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "revisions": [
                {
                    "revision_no": r.revision_no,
                    "operation": r.operation,
                    "rewrite_id": r.rewrite_id,
                    "field_count": len(r.snapshot or []),
                    "created_at": r.created_at.isoformat(),
                }
                for r in revisions
            ],
        }

    def list_rewrites(self, resume_id: str) -> dict:
        self._get_resume(resume_id)
        records = (
            self.db.execute(
                select(RewriteResult)
                .where(RewriteResult.resume_id == resume_id)
                .order_by(RewriteResult.created_at.desc())
            )
            .scalars()
            .all()
        )
        return {
            "resume_id": resume_id,
            "rewrites": [
                {
                    "rewrite_id": r.id,
                    "issue_id": r.issue_id,
                    "target_field": r.target_field,
                    "status": r.status,
                    "risk_level": r.risk_level,
                    "before": r.before,
                    "after": r.after,
                    "applied": r.applied,
                    "change_point_count": len(r.change_points or []),
                    "fact_check_passed": (r.fact_check or {}).get("passed"),
                    "model_version": r.model_version,
                }
                for r in records
            ],
        }

    # ---------- O-05 导出并自动复检 ----------
    def export(self, draft_id: str) -> dict:
        draft = self._get_draft(draft_id)
        lines = fields_to_lines(draft.fields or [])

        export_dir = UPLOAD_DIR / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        base_name = f"resume-{draft.resume_id[:8]}-v{draft.current_version}-{stamp}"

        txt_path = export_dir / f"{base_name}.txt"
        txt_path.write_text("\n".join(lines), encoding="utf-8")

        docx_path = self._write_docx(lines, export_dir / f"{base_name}.docx")

        draft.status = DraftStatus.EXPORTED
        self.db.flush()

        recheck = self.recheck(draft)
        self.db.commit()

        return {
            "draft_id": draft.id,
            "current_version": draft.current_version,
            "files": {
                "txt": str(txt_path.relative_to(UPLOAD_DIR)),
                "docx": str(docx_path.relative_to(UPLOAD_DIR)),
            },
            "recheck": recheck,
        }

    def _write_docx(self, lines: list[str], path: Path) -> Path:
        """用 python-docx 生成可交付的 Word 文件（O-05 层 2：只做内容，不做排版美化）。"""
        try:
            from docx import Document

            document = Document()
            for line in lines:
                if not line.strip():
                    continue
                paragraph = document.add_paragraph(line.strip())
                # 章节标题加粗，便于阅读；不做任何排版美化
                if line.strip() in _DOCX_HEADINGS:
                    for run in paragraph.runs:
                        run.bold = True
            document.save(str(path))
            return path
        except Exception as exc:  # pragma: no cover - 依赖或磁盘异常
            raise BizError(500, f"生成 Word 文件失败：{type(exc).__name__}")

    # ---------- 复检：草稿重新走一遍"解析 → 诊断" ----------
    def recheck(self, draft: ResumeDraft) -> dict:
        """O-05 闭环：导出后自动触发一次复检。

        必须用草稿内容**重新解析**（而不是直接拿字段跑诊断），
        否则拿不到 ATS 结论——没有解析轨迹就无法判断机器读到了什么。
        """
        lines = fields_to_lines(draft.fields or [])
        parsed = structure_document(lines, PARSE_RULE_VERSION)
        results = run_diagnosis(
            resume_id=draft.resume_id,
            structure=parsed.structure,
            trace=parsed.trace,
            unrecognized=parsed.unrecognized,
            dimensions=[DIM_NORM, DIM_CONTENT, DIM_MACHINE],
        )
        report = build_report(draft.resume_id, results)
        machine = next((r for r in results if r.dimension == DIM_MACHINE), None)
        return {
            "total_score": report["total_score"],
            "dimension_scores": report["dimension_scores"],
            "issue_count": report["issue_summary"]["total"],
            "verdict_summary": (machine.meta.get("verdict_summary") if machine else {}),
            "rule_version": PARSE_RULE_VERSION,
            "field_count": len(parsed.structure.get("education", []))
            + len(parsed.structure.get("experience", []))
            + len(parsed.structure.get("projects", []))
            + len(parsed.structure.get("skills", [])),
            "unrecognized_count": len(parsed.unrecognized or []),
        }

    # ---------- O-09 优化前后对比 ----------
    def comparison(self, draft_id: str) -> dict:
        draft = self._get_draft(draft_id)
        resume = self._get_resume(draft.resume_id)

        # 优化前基准：最近一次解析结果 + 综合报告
        parse = self.db.execute(
            select(ParseResult)
            .where(ParseResult.resume_id == draft.resume_id)
            .order_by(ParseResult.created_at.desc())
        ).scalars().first()
        if parse is None:
            raise BizError(ErrorCode.PARSE_FAILED, "缺少解析基准，无法对比")

        before_results = run_diagnosis(
            resume_id=draft.resume_id,
            structure=parse.structure or {},
            trace=parse.trace or [],
            unrecognized=parse.unrecognized or [],
            dimensions=[DIM_NORM, DIM_CONTENT, DIM_MACHINE],
        )
        before_report = build_report(draft.resume_id, before_results)
        before_machine = next(r for r in before_results if r.dimension == DIM_MACHINE)
        before_verdicts = before_machine.meta.get("verdict_summary", {})

        # 优化后：对草稿复检
        after = self.recheck(draft)
        after_verdicts = after["verdict_summary"] or {}

        # 同类对比约束：解析器/规则版本不一致 → 6006（设计文档 4.5.6 实现要点）
        if parse.rule_version != PARSE_RULE_VERSION:
            raise BizError(
                ErrorCode.COMPARISON_NOT_COMPARABLE,
                f"解析规则版本不一致（{parse.rule_version} vs {PARSE_RULE_VERSION}），对比结论不可比",
            )

        # parse_diff：被"救回来"的字段（优化前丢失/错位，优化后正确读取）
        before_bad = {
            pt["field"]
            for pt in before_machine.meta.get("parse_trace", [])
            if pt.get("verdict") in ("lost", "misplaced")
        }
        after_good = {
            pt["field"]
            for pt in self._recheck_trace(draft)
            if pt.get("verdict") == "correct"
        }
        recovered = sorted(before_bad & after_good)

        score_diff = {}
        for dim, info in before_report["dimension_scores"].items():
            after_score = after["dimension_scores"].get(dim, {}).get("score", 0)
            score_diff[dim] = {
                "label": info["label"],
                "before": info["score"],
                "after": after_score,
                "delta": after_score - info["score"],
            }

        return {
            "resume_id": draft.resume_id,
            "draft_id": draft.id,
            "parser_version": {"before": parse.rule_version, "after": PARSE_RULE_VERSION},
            "score_diff": {
                "before": before_report["total_score"],
                "after": after["total_score"],
                "delta": after["total_score"] - before_report["total_score"],
                "dimensions": score_diff,
            },
            "content_diff": self._content_diff(draft.id),
            "parse_diff": {
                "before": before_verdicts,
                "after": after_verdicts,
                "recovered": recovered,
                "issue_count": {"before": before_report["issue_summary"]["total"], "after": after["issue_count"]},
            },
        }

    def _recheck_trace(self, draft: ResumeDraft) -> list[dict]:
        lines = fields_to_lines(draft.fields or [])
        parsed = structure_document(lines, PARSE_RULE_VERSION)
        results = run_diagnosis(
            resume_id=draft.resume_id,
            structure=parsed.structure,
            trace=parsed.trace,
            unrecognized=parsed.unrecognized,
            dimensions=[DIM_MACHINE],
        )
        return results[0].meta.get("parse_trace", []) if results else []

    def _content_diff(self, draft_id: str) -> list[dict]:
        """内容差异：来自 Revision 记录（来源可追溯，不重新比对文本）。"""
        revisions = (
            self.db.execute(
                select(Revision)
                .where(Revision.draft_id == draft_id, Revision.operation.in_(_CONTENT_OPS))
                .order_by(Revision.revision_no)
            )
            .scalars()
            .all()
        )
        return [
            {
                "revision_no": r.revision_no,
                "operation": r.operation,
                "rewrite_id": r.rewrite_id,
                "created_at": r.created_at.isoformat(),
            }
            for r in revisions
        ]

    # ---------- 内部：字段与版本操作 ----------
    def _set_field(self, draft: ResumeDraft, field_name: str, value: str, source: str) -> None:
        if not field_name:
            raise BizError(ErrorCode.REWRITE_TARGET_NOT_FOUND, "未指定目标字段")
        for f in draft.fields or []:
            if f.get("field_name") == field_name:
                f["value"] = value
                f["source"] = source
                f["version_no"] = draft.current_version + 1
                self._touch_fields(draft)
                return
        # 草稿中没有该字段（新增字段）：追加，保证应用不会静默丢失
        (draft.fields or []).append(
            {
                "field_name": field_name,
                "value": value,
                "source": source,
                "version_no": draft.current_version + 1,
            }
        )
        self._touch_fields(draft)

    @staticmethod
    def _touch_fields(draft: ResumeDraft) -> None:
        """标记 JSON 字段已变更。

        SQLAlchemy 的 JSON 类型**不会**追踪列表/字典内部的就地修改——
        不显式标记的话，改完值不会产生 UPDATE，版本号却已经递增，
        于是快照里存的仍是旧内容，撤销也"恢复"不回任何东西。这类静默失败极难察觉。
        """
        draft.fields = list(draft.fields or [])
        flag_modified(draft, "fields")

    def _snapshot(self, draft: ResumeDraft, operation: str, rewrite_id: str | None = None) -> None:
        next_no = self._next_revision_no(draft.id)
        draft.current_version = next_no
        self.db.add(
            Revision(
                draft_id=draft.id,
                revision_no=next_no,
                snapshot=copy.deepcopy(draft.fields),
                operation=operation,
                rewrite_id=rewrite_id,
            )
        )
        self.db.flush()
        self._prune_revisions(draft.id)

    def _next_revision_no(self, draft_id: str) -> int:
        current = (
            self.db.execute(
                select(Revision.revision_no)
                .where(Revision.draft_id == draft_id)
                .order_by(Revision.revision_no.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        return (current or 0) + 1

    def _prune_revisions(self, draft_id: str) -> None:
        """版本上限清理：保留首版 + 最近 N-1 版（设计文档 4.5.5）。"""
        revisions = (
            self.db.execute(
                select(Revision)
                .where(Revision.draft_id == draft_id)
                .order_by(Revision.revision_no.desc())
            )
            .scalars()
            .all()
        )
        if len(revisions) <= MAX_REVISIONS:
            return
        keep = {r.revision_no for r in revisions[: MAX_REVISIONS - 1]}
        keep.add(1)  # 首版是撤销链的起点，必须保留
        for r in revisions:
            if r.revision_no not in keep:
                self.db.delete(r)

    def _draft_payload(self, draft: ResumeDraft) -> dict:
        return {
            "draft_id": draft.id,
            "resume_id": draft.resume_id,
            "jd_id": draft.jd_id,
            "current_version": draft.current_version,
            "status": draft.status,
            "fields": draft.fields or [],
            "field_count": len(draft.fields or []),
            "rewritten_count": sum(
                1 for f in draft.fields or [] if f.get("source") == "rewritten"
            ),
            "created_at": draft.created_at.isoformat(),
        }
