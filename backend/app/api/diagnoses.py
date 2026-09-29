"""诊断相关 API 路由（设计文档 7.1 接口清单 #3/#4/#5/#6/#7）。"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApiResponse, DiagnoseRequest, JdSubmitRequest, ok
from app.services.diagnosis_service import DiagnosisService
from app.services.report_export import ReportExportService

router = APIRouter(tags=["diagnosis"])


@router.post(
    "/job-descriptions",
    response_model=ApiResponse,
    summary="提交岗位描述（FR-08）",
)
def submit_jd(payload: JdSubmitRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = DiagnosisService(db).submit_jd(payload.title, payload.raw_text)
    return ok(data, message="岗位描述已提交")


@router.post(
    "/diagnoses",
    response_model=ApiResponse,
    summary="发起诊断，可指定维度（FR-04/05/06/08）",
)
def run_diagnosis(payload: DiagnoseRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = DiagnosisService(db).run(
        resume_id=payload.resume_id,
        dimensions=payload.dimensions,
        jd_id=payload.jd_id,
    )
    return ok(data, message="诊断完成")


@router.get(
    "/diagnoses/{diagnosis_id}",
    response_model=ApiResponse,
    summary="查询诊断结果（FR-04/05/06/08）",
)
def get_diagnosis(diagnosis_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(DiagnosisService(db).get_diagnosis(diagnosis_id))


@router.get(
    "/reports/{resume_id}",
    response_model=ApiResponse,
    summary="获取综合报告：健康分 + 按优先级排序的问题清单（FR-10/11）",
)
def get_report(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(DiagnosisService(db).get_report(resume_id))


@router.get(
    "/reports/{resume_id}/export",
    summary="导出诊断报告为自包含 HTML（FR-13）",
    # 文件下载不走统一响应格式（code/message/data），直接返回 HTML 字节流
    response_class=Response,
    responses={200: {"content": {"text/html": {}}, "description": "可直接打开或打印为 PDF 的报告"}},
)
def export_report(resume_id: str, db: Session = Depends(get_db)) -> Response:
    html, filename = ReportExportService(db).export_html(resume_id)
    return Response(
        content=html,
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Resume-Id": resume_id,
        },
    )
