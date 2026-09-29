"""诊断业务服务：JD 提交 → 诊断编排 → 结果落库 → 综合报告（设计文档 5.1 / 7.1 接口 #3-#6）。

分层边界（设计文档 4.1）：本层只做编排与整合，**不包含任何诊断规则**——
规则全部在 app/diagnosis/ 下的模块里，因此模块可脱离服务单独测试（NFR-07）。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diagnosis.match import extract_jd_keys
from app.diagnosis.models import (
    DIMENSION_LABELS,
    SEVERITY_LABELS,
    DiagnosisResult,
)
from app.diagnosis.runner import (
    ALL_DIMENSIONS,
    build_report,
    run_diagnosis,
)
from app.errors import BizError, ErrorCode
from app.models import Diagnosis, Issue, JobDescription, ParseResult, Report, Resume


class DiagnosisService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 内部：取简历与解析结果 ----------
    def _get_resume(self, resume_id: str) -> Resume:
        resume = self.db.get(Resume, resume_id)
        # 软删除的简历视同不存在（NFR-05：删除后不可再访问）
        if resume is None or resume.deleted_at is not None:
            raise BizError(ErrorCode.RESUME_NOT_FOUND)
        return resume

    def _get_parse_result(self, resume_id: str) -> ParseResult:
        stmt = (
            select(ParseResult)
            .where(ParseResult.resume_id == resume_id)
            .order_by(ParseResult.created_at.desc())
        )
        result = self.db.execute(stmt).scalars().first()
        if result is None:
            raise BizError(ErrorCode.PARSE_FAILED, "该简历尚未完成解析，无法诊断")
        return result

    # ---------- 岗位描述（FR-08 输入） ----------
    def submit_jd(self, title: str, raw_text: str) -> dict:
        if not raw_text or len(raw_text.strip()) < 10:
            raise BizError(ErrorCode.JD_TOO_SHORT)

        keys = extract_jd_keys(raw_text)
        jd = JobDescription(
            title=(title or "").strip()[:200],
            raw_text=raw_text,
            extracted_keys=keys,
        )
        self.db.add(jd)
        self.db.flush()
        self.db.commit()
        return {
            "jd_id": jd.id,
            "title": jd.title,
            "extracted_keys": keys,
            "created_at": jd.created_at.isoformat(),
        }

    def _get_jd(self, jd_id: str) -> dict:
        jd = self.db.get(JobDescription, jd_id)
        if jd is None:
            raise BizError(ErrorCode.JOB_DESC_NOT_FOUND)
        return {
            "id": jd.id,
            "title": jd.title,
            "raw_text": jd.raw_text,
            "extracted_keys": jd.extracted_keys or {},
        }

    # ---------- 发起诊断（接口 #4） ----------
    def run(
        self,
        resume_id: str,
        dimensions: list[str] | None = None,
        jd_id: str | None = None,
    ) -> dict:
        self._get_resume(resume_id)
        parse = self._get_parse_result(resume_id)

        dims = dimensions or ALL_DIMENSIONS
        invalid = [d for d in dims if d not in ALL_DIMENSIONS]
        if invalid:
            raise BizError(
                ErrorCode.PARSE_FAILED,
                f"未知诊断维度 {invalid}，可选：{list(DIMENSION_LABELS)}",
            )

        # 岗位匹配维度必须提供 JD（设计文档 4.4：比对基准是岗位描述）
        jd = None
        if jd_id:
            jd = self._get_jd(jd_id)
        elif "match" in dims:
            dims = [d for d in dims if d != "match"]

        results = run_diagnosis(
            resume_id=resume_id,
            structure=parse.structure or {},
            trace=parse.trace or [],
            unrecognized=parse.unrecognized or [],
            dimensions=dims,
            jd=jd,
        )
        if not results:
            raise BizError(ErrorCode.PARSE_FAILED, "没有可执行的诊断维度")

        diagnosis_ids: list[str] = []
        for result in results:
            diagnosis_ids.append(self._persist(result, jd_id=jd.get("id") if jd else None))

        report = build_report(resume_id, results)
        # 必须带上 diagnosis_ids：前端诊断完成后要据此拉取各维度明细
        # （ATS 四类结论、岗位匹配要求清单都存在 meta 里），否则报告页缺两大块内容。
        report["diagnosis_ids"] = diagnosis_ids
        self._save_report(resume_id, report)
        self.db.commit()
        return report

    def _persist(self, result: DiagnosisResult, jd_id: str | None) -> str:
        """落库一次诊断及其问题项，返回诊断记录 ID。"""
        diagnosis = Diagnosis(
            resume_id=result.resume_id,
            jd_id=jd_id,
            dimension=result.dimension,
            module_name=result.module_name,
            score=result.score,
            status="success",
            fingerprint=result.result_id,  # 确定性内容指纹，支撑可复现性断言
            meta=result.to_dict()["meta"],
        )
        self.db.add(diagnosis)
        self.db.flush()
        for issue in result.issues:
            self.db.add(
                Issue(
                    diagnosis_id=diagnosis.id,
                    issue_code=issue.issue_id,
                    severity=issue.severity,
                    category=issue.category,
                    location={
                        "field": issue.location.field,
                        "snippet": issue.location.snippet,
                        "offset": issue.location.offset,
                    },
                    problem=issue.problem,
                    suggestion=issue.suggestion,
                    evidence=issue.evidence,
                    confidence=issue.confidence,
                )
            )
        return diagnosis.id

    def _save_report(self, resume_id: str, report: dict) -> None:
        """报告与简历一对一：重复诊断时刷新，保证拿到的始终是最新结论。"""
        existing = self.db.execute(
            select(Report).where(Report.resume_id == resume_id)
        ).scalars().first()
        if existing is None:
            self.db.add(
                Report(
                    resume_id=resume_id,
                    total_score=report["total_score"],
                    dimension_scores=report["dimension_scores"],
                    issue_summary=report["issue_summary"],
                )
            )
        else:
            existing.total_score = report["total_score"]
            existing.dimension_scores = report["dimension_scores"]
            existing.issue_summary = report["issue_summary"]

    # ---------- 查询诊断结果（接口 #5） ----------
    def get_diagnosis(self, diagnosis_id: str) -> dict:
        diagnosis = self.db.get(Diagnosis, diagnosis_id)
        if diagnosis is None:
            raise BizError(ErrorCode.DIAGNOSIS_NOT_FOUND)
        # 纵深防御：即使简历被删除时漏清了衍生数据，也读不到其中的敏感内容（NFR-05）
        self._get_resume(diagnosis.resume_id)
        issues = (
            self.db.execute(
                select(Issue).where(Issue.diagnosis_id == diagnosis.id)
            )
            .scalars()
            .all()
        )
        return {
            "result_id": diagnosis.id,
            "fingerprint": diagnosis.fingerprint,
            "resume_id": diagnosis.resume_id,
            "jd_id": diagnosis.jd_id,
            "dimension": diagnosis.dimension,
            "dimension_label": DIMENSION_LABELS.get(diagnosis.dimension, ""),
            "module_name": diagnosis.module_name,
            "score": diagnosis.score,
            "status": diagnosis.status,
            "meta": diagnosis.meta or {},
            "issues": [
                {
                    "issue_id": i.issue_code,
                    "severity": i.severity,
                    "severity_label": SEVERITY_LABELS.get(i.severity, i.severity),
                    "category": i.category,
                    "location": i.location,
                    "problem": i.problem,
                    "suggestion": i.suggestion,
                    "evidence": i.evidence,
                    "confidence": i.confidence,
                }
                for i in issues
            ],
            "created_at": diagnosis.created_at.isoformat(),
        }

    # ---------- 综合报告（接口 #6） ----------
    def get_report(self, resume_id: str) -> dict:
        self._get_resume(resume_id)
        report = self.db.execute(
            select(Report).where(Report.resume_id == resume_id)
        ).scalars().first()
        if report is None:
            raise BizError(ErrorCode.DIAGNOSIS_NOT_FOUND, "该简历尚未诊断，请先发起诊断")

        diagnoses = (
            self.db.execute(
                select(Diagnosis)
                .where(Diagnosis.resume_id == resume_id)
                .order_by(Diagnosis.created_at.desc())
            )
            .scalars()
            .all()
        )
        # 完整问题清单（含 evidence / confidence）——报告整合层只存简要条目，
        # 判定依据需回查 Issue 表，否则前端无法向用户解释"凭什么这么判"（原则三）。
        issues = (
            self.db.execute(
                select(Issue)
                .join(Diagnosis, Issue.diagnosis_id == Diagnosis.id)
                .where(Diagnosis.resume_id == resume_id)
            )
            .scalars()
            .all()
        )
        return {
            "resume_id": resume_id,
            "total_score": report.total_score,
            "dimension_scores": report.dimension_scores or {},
            "issue_summary": report.issue_summary or {},
            "issues": [
                {
                    "issue_id": i.issue_code,
                    "severity": i.severity,
                    "severity_label": SEVERITY_LABELS.get(i.severity, i.severity),
                    "category": i.category,
                    "location": i.location,
                    "problem": i.problem,
                    "suggestion": i.suggestion,
                    "evidence": i.evidence,
                    "confidence": i.confidence,
                }
                for i in issues
            ],
            "diagnosis_ids": [d.id for d in diagnoses],
            "created_at": report.created_at.isoformat(),
        }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
