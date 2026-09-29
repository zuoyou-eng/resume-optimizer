"""亮点挖掘相关 API 路由（FR-09 引导式亮点挖掘，V1.2 弹性项）。

四个端点对应需求的完整语义链：
  候选清单（哪些经历值得挖）→ 追问序列（缺什么问什么）
  → 合成预览（**不落库**）→ 确认写入（用户确认后才进草稿并产生新版本）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ApiResponse,
    HighlightComposeRequest,
    HighlightConfirmRequest,
    HighlightFieldRequest,
    ok,
)
from app.services.highlight_service import HighlightService

router = APIRouter(tags=["highlight"])


@router.get(
    "/resumes/{resume_id}/highlight-candidates",
    response_model=ApiResponse,
    summary="可挖掘亮点的平淡经历清单（FR-09）",
)
def list_candidates(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    data = HighlightService(db).candidates(resume_id)
    return ok(data, message="候选清单已生成")


@router.post(
    "/highlights/questions",
    response_model=ApiResponse,
    summary="生成分层追问序列（FR-09）",
)
def build_questions(payload: HighlightFieldRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = HighlightService(db).questions(payload.resume_id, payload.field_name)
    return ok(data, message="追问序列已生成")


@router.post(
    "/highlights/compose",
    response_model=ApiResponse,
    summary="合成候选描述预览（FR-09，不落库）",
)
def compose_preview(payload: HighlightComposeRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = HighlightService(db).compose(payload.resume_id, payload.field_name, payload.answers)
    return ok(data, message="预览已生成（未写入）")


@router.post(
    "/highlights/confirm",
    response_model=ApiResponse,
    summary="确认写入草稿并产生新版本（FR-09）",
)
def confirm_write(payload: HighlightConfirmRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = HighlightService(db).confirm(
        payload.resume_id, payload.field_name, payload.after_text, payload.answers
    )
    return ok(data, message="已写入草稿")
