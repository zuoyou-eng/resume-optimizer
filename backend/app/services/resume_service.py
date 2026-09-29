"""简历业务服务：上传 → 校验 → 解析 → 落库 的编排（设计文档 5.1：解析与诊断两步的起点）。"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import BizError, ErrorCode
from app.models import (
    Diagnosis,
    Issue,
    ParseResult,
    Report,
    Resume,
    ResumeDraft,
    Revision,
    RewriteResult,
)
from app.parser.factory import get_extractor
from app.parser.structurer import structure_document
from app.services.storage import file_sha256, save_upload

# 魔术字节签名：防止伪装扩展名上传可执行内容（设计文档第 9 章）
# 结构为「备选签名列表」：外层任一备选命中即通过（与原实现一致），
# 单个备选内的多个 (偏移, 字节) 必须全部命中——用于 WebP 这类复合文件头
# （"RIFF" 与 WAV/AVI 共用，必须再看第 8 字节起的 "WEBP" 才能确认）。
_MAGIC_SIGNATURES: dict[str, list[list[tuple[int, bytes]]]] = {
    ".pdf": [[(0, b"%PDF")]],
    ".docx": [[(0, b"PK\x03\x04")], [(0, b"PK\x05\x06")]],
    # 图片格式（FR-01）：按文件头识别，防止把可执行文件改名成 .png 上传
    ".png": [[(0, b"\x89PNG\r\n\x1a\n")]],
    ".jpg": [[(0, b"\xff\xd8\xff")]],
    ".jpeg": [[(0, b"\xff\xd8\xff")]],
    ".gif": [[(0, b"GIF87a")], [(0, b"GIF89a")]],
    ".bmp": [[(0, b"BM")]],
    ".webp": [[(0, b"RIFF"), (8, b"WEBP")]],
}


def _magic_ok(ext: str, content: bytes) -> bool:
    """按签名校验文件内容：任一备选签名全部命中即为通过。"""
    alternatives = _MAGIC_SIGNATURES.get(ext)
    if not alternatives:
        return True  # 未登记的类型不做事魔术校验
    return any(
        all(content[offset : offset + len(sig)] == sig for offset, sig in alt)
        for alt in alternatives
    )


class ResumeService:
    def __init__(self, db: Session):
        self.db = db

    # ---------- 上传（FR-01）+ 同步解析（FR-02） ----------
    def upload(self, filename: str, content: bytes) -> dict:
        ext = Path(filename).suffix.lower()

        # 校验 1：类型（扩展名 + 魔术字节双重校验）
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise BizError(ErrorCode.FILE_TYPE_NOT_SUPPORTED)
        if not content:
            raise BizError(ErrorCode.FILE_EMPTY)
        signatures = _MAGIC_SIGNATURES.get(ext)
        if signatures and not _magic_ok(ext, content):
            raise BizError(
                ErrorCode.FILE_TYPE_NOT_SUPPORTED,
                "文件内容与扩展名不符，请上传真实的简历文件",
            )

        # 校验 2：大小
        if len(content) > settings.max_file_size_bytes:
            raise BizError(ErrorCode.FILE_TOO_LARGE)

        rel_path, abs_path = save_upload(filename, content)
        resume = Resume(
            original_name=filename,
            file_path=rel_path,
            file_type=ext,
            file_hash=file_sha256(content),
            file_size=len(content),
            status="uploaded",
        )
        self.db.add(resume)
        self.db.flush()

        # 同步解析（MVP：同步执行；后续可替换为异步任务，服务层接口不变）
        extractor = get_extractor(ext)
        if extractor is None:  # pragma: no cover
            raise BizError(ErrorCode.FILE_TYPE_NOT_SUPPORTED)
        try:
            doc = extractor.extract(str(abs_path))
        except BizError as e:
            self._mark_parse_failed(resume, e.message)
            self.db.commit()
            raise

        if not doc.paragraphs:
            self._mark_parse_failed(resume, "未能从文件中提取到任何文本内容（可能为图片版或空文件）")
            self.db.commit()
            raise BizError(ErrorCode.FILE_EMPTY)

        result = structure_document(doc.paragraphs, settings.RULE_VERSION)
        self.db.add(
            ParseResult(
                resume_id=resume.id,
                structure=result.structure,
                trace=result.trace,
                unrecognized=result.unrecognized,
                rule_version=settings.RULE_VERSION,
                parse_status="success",
            )
        )
        resume.status = "parsed"
        self.db.commit()

        return {
            "resume_id": resume.id,
            "status": resume.status,
            "rule_version": settings.RULE_VERSION,
            "structure": result.structure,
            "trace": result.trace,
            "unrecognized": result.unrecognized,
        }

    def _mark_parse_failed(self, resume: Resume, message: str) -> None:
        resume.status = "parse_failed"
        self.db.add(
            ParseResult(
                resume_id=resume.id,
                structure={},
                trace=[],
                unrecognized=[],
                rule_version=settings.RULE_VERSION,
                parse_status="failed",
                error_message=message,
            )
        )

    # ---------- 查询结构化结果（FR-02/03） ----------
    def get_structure(self, resume_id: str) -> dict:
        resume = self._get_active(resume_id)
        parse_result = self.db.scalar(
            select(ParseResult)
            .where(ParseResult.resume_id == resume.id)
            .order_by(ParseResult.created_at.desc())
            .limit(1)
        )
        if parse_result is None:
            raise BizError(ErrorCode.RESUME_NOT_FOUND, "该简历尚无解析结果")
        return {
            "resume_id": resume.id,
            "original_name": resume.original_name,
            "parse_status": parse_result.parse_status,
            "rule_version": parse_result.rule_version,
            "structure": parse_result.structure,
            "trace": parse_result.trace,
            "unrecognized": parse_result.unrecognized,
            "created_at": parse_result.created_at.isoformat(),
        }

    # ---------- 列表 ----------
    def list_resumes(self) -> list[dict]:
        rows = self.db.scalars(
            select(Resume)
            .where(Resume.deleted_at.is_(None))
            .order_by(Resume.created_at.desc())
        ).all()
        return [
            {
                "id": r.id,
                "original_name": r.original_name,
                "file_type": r.file_type,
                "file_size": r.file_size,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    # ---------- 删除（NFR-05：软删除，后续接定期物理清理） ----------
    def delete(self, resume_id: str) -> dict:
        resume = self._get_active(resume_id)
        resume.deleted_at = datetime.now(timezone.utc)

        # 接口 #8 语义是"删除简历及其全部衍生数据"：软删除只置 deleted_at，
        # ORM 级联不会触发，衍生数据会残留在库中仍可被读取——
        # 这对含敏感个人信息的简历是隐私缺陷（NFR-05），因此这里显式物理清除。
        # 注意顺序：先删依赖子表的记录（Issue→Diagnosis、Revision→Draft、RewriteResult）。
        from sqlalchemy import delete as sa_delete

        diagnosis_ids = [
            d.id for d in self.db.query(Diagnosis.id).filter(Diagnosis.resume_id == resume.id)
        ]
        if diagnosis_ids:
            self.db.execute(sa_delete(Issue).where(Issue.diagnosis_id.in_(diagnosis_ids)))
            self.db.execute(sa_delete(Diagnosis).where(Diagnosis.resume_id == resume.id))
        self.db.execute(sa_delete(Report).where(Report.resume_id == resume.id))

        draft_ids = [
            d.id for d in self.db.query(ResumeDraft.id).filter(ResumeDraft.resume_id == resume.id)
        ]
        if draft_ids:
            self.db.execute(sa_delete(Revision).where(Revision.draft_id.in_(draft_ids)))
            self.db.execute(sa_delete(ResumeDraft).where(ResumeDraft.resume_id == resume.id))
        self.db.execute(sa_delete(RewriteResult).where(RewriteResult.resume_id == resume.id))

        self.db.commit()
        return {
            "deleted": True,
            "resume_id": resume.id,
            "diagnoses_removed": len(diagnosis_ids),
            "drafts_removed": len(draft_ids),
        }

    def _get_active(self, resume_id: str) -> Resume:
        resume = self.db.get(Resume, resume_id)
        if resume is None or resume.deleted_at is not None:
            raise BizError(ErrorCode.RESUME_NOT_FOUND)
        return resume
