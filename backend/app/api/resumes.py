"""简历相关 API 路由（设计文档 7.1 接口清单 #1/#2/#8 + 列表）。"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApiResponse, ok
from app.services.resume_service import ResumeService

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", response_model=ApiResponse, summary="上传简历并同步解析")
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ApiResponse:
    content = await file.read()
    service = ResumeService(db)
    data = service.upload(file.filename or "unknown", content)
    return ok(data, message="上传并解析成功")


@router.get("", response_model=ApiResponse, summary="简历列表")
def list_resumes(db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResumeService(db).list_resumes())


@router.get("/{resume_id}", response_model=ApiResponse, summary="简历元信息")
def get_resume(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResumeService(db).get_structure(resume_id))


@router.get(
    "/{resume_id}/structure",
    response_model=ApiResponse,
    summary="获取结构化解析结果与解析轨迹（FR-02/03）",
)
def get_structure(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResumeService(db).get_structure(resume_id))


@router.delete("/{resume_id}", response_model=ApiResponse, summary="删除简历（软删除）")
def delete_resume(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(ResumeService(db).delete(resume_id), message="已删除")
