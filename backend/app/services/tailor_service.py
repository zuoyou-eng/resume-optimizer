"""O-08 定制版本生成服务：依据 FR-08 匹配结果生成面向该岗位的草稿版本。

需求红线：**只做取舍与重组，不新增事实**。服务层三重保证：
  1. 必须存在针对该 JD 的 match 诊断（定制不能凭空生成）；
  2. 重排前后字段值的多重集完全一致（服务端复核，防止逻辑缺陷改到值）；
  3. 无移动时不产生空版本（版本历史只记录真实变更）。
落点复用既有版本机制：全量快照 + operation="tailor"，可回滚（NFR-10）。
"""
import copy
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BizError, ErrorCode
from app.models import Diagnosis, JobDescription, ParseResult, Resume, ResumeDraft, Revision
from app.optimize.tailor import plan_tailored


class TailorService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- O-08 生成定制版本 ----------
    def tailor(self, resume_id: str, jd_id: str) -> dict:
        resume = self._get_resume(resume_id)
        jd = self.db.get(JobDescription, jd_id)
        if jd is None:
            raise BizError(ErrorCode.JOB_DESC_NOT_FOUND)

        match_meta = self._latest_match_meta(resume_id, jd_id)
        if match_meta is None:
            raise BizError(
                ErrorCode.TAILOR_NO_MATCH,
                "该简历尚未针对此岗位诊断：请先提交 JD 并完成诊断，再生成定制版本",
            )

        draft = self._get_or_create_draft(resume_id, jd_id)
        plan = plan_tailored(draft.fields or [], match_meta)

        if not plan.changed:
            # 无移动不产生空版本（版本历史只记录真实变更）
            return {
                "draft_id": draft.id,
                "resume_id": resume_id,
                "jd_id": jd_id,
                "jd_title": plan.jd_title or jd.title,
                "changed": False,
                "current_version": draft.current_version,
                "moves": [],
                "message": "当前字段顺序已贴合该岗位，无需调整",
            }

        self._verify_values_preserved(draft.fields or [], plan.fields)

        draft.fields = copy.deepcopy(plan.fields)
        # 定制版本记录目标岗位（设计文档 4.5.5：jd_id 为空表示通用版本）
        draft.jd_id = jd_id
        self._snapshot(draft, operation="tailor")
        self.db.commit()

        return {
            "draft_id": draft.id,
            "resume_id": resume_id,
            "jd_id": jd_id,
            "jd_title": plan.jd_title or jd.title,
            "changed": True,
            "current_version": draft.current_version,
            "requirement_count": plan.requirement_count,
            "gap_count": plan.gap_count,
            "moves": [
                {
                    "field_name": m.field_name,
                    "action": m.action,
                    "from_index": m.from_index,
                    "to_index": m.to_index,
                    "hits": m.hits,
                    "reason": m.reason,
                }
                for m in plan.moves
            ],
        }

    # ---------- 内部 ----------
    def _get_resume(self, resume_id: str) -> Resume:
        resume = self.db.get(Resume, resume_id)
        if resume is None or resume.deleted_at is not None:
            raise BizError(ErrorCode.RESUME_NOT_FOUND)
        return resume

    def _latest_match_meta(self, resume_id: str, jd_id: str) -> dict | None:
        """取该简历针对该 JD 的最新一次 match 维度诊断 meta（FR-08 结果的唯一来源）。"""
        row = (
            self.db.execute(
                select(Diagnosis)
                .where(
                    Diagnosis.resume_id == resume_id,
                    Diagnosis.jd_id == jd_id,
                    Diagnosis.dimension == "match",
                )
                .order_by(Diagnosis.created_at.desc())
            )
            .scalars()
            .first()
        )
        return row.meta if row is not None else None

    def _get_or_create_draft(self, resume_id: str, jd_id: str | None = None) -> ResumeDraft:
        """与 RewriteService 同策略：取最新草稿；没有则从解析结果初始化（O-04）。"""
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

        # 未识别内容一并进草稿（FR-03，与 RewriteService 保持一致）
        from app.optimize.draft_fields import structure_to_fields

        draft = ResumeDraft(
            resume_id=resume_id,
            jd_id=jd_id,
            fields=structure_to_fields(parse.structure or {}, parse.unrecognized or []),
            current_version=1,
            status="draft",
        )
        self.db.add(draft)
        self.db.flush()
        self._snapshot(draft, operation="init")
        return draft

    @staticmethod
    def _verify_values_preserved(before: list[dict], after: list[dict]) -> None:
        """事实守恒复核：重排只许换顺序，字段值多重集必须逐一对应。

        比 facts 比对更严格——连值本身都不允许变化。不通过即 6002 拒绝，
        且不写入任何数据（设计文档 4.5.7：宁可失败也不返回可能编造的内容）。
        """
        before_values = Counter(str(f.get("value") or "") for f in before)
        after_values = Counter(str(f.get("value") or "") for f in after)
        if before_values != after_values:
            raise BizError(
                ErrorCode.REWRITE_FACT_CHECK_FAILED,
                "定制版本改变了字段内容，已拒绝生成（只允许调整顺序）",
            )

    def _snapshot(self, draft: ResumeDraft, operation: str) -> None:
        next_no = (
            self.db.execute(
                select(Revision.revision_no)
                .where(Revision.draft_id == draft.id)
                .order_by(Revision.revision_no.desc())
                .limit(1)
            )
            .scalars()
            .first()
            or 0
        ) + 1
        draft.current_version = next_no
        self.db.add(
            Revision(
                draft_id=draft.id,
                revision_no=next_no,
                snapshot=copy.deepcopy(draft.fields),
                operation=operation,
            )
        )
        self.db.flush()
