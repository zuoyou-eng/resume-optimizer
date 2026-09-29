"""优化模块 API 路由（设计文档 7.1 接口清单 #9-#18）。

风险等级校验统一在服务端完成（O-07 硬约束 2）：路由层不做任何 risk_level 判断，
即使前端传入了 needs_review 的改写 ID，也会由服务层返回 6003。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import BizError, ErrorCode
from app.optimize.ai_engine import DEFAULT_TIMEOUT_SECONDS, build_engine
from app.schemas import (
    ApiResponse,
    BatchApplyRequest,
    GenerateRewriteRequest,
    ManualEditRequest,
    ModelSettings,
    RollbackRequest,
    ok,
)
from app.services.rewrite_service import RewriteService

router = APIRouter(tags=["optimize"])


@router.post("/rewrites", response_model=ApiResponse, summary="基于问题项发起改写（O-01/02）")
def generate_rewrite(payload: GenerateRewriteRequest, db: Session = Depends(get_db)) -> ApiResponse:
    # model_settings 为 None 时用确定性规则引擎；传入则本次请求改用用户自带模型。
    return ok(
        RewriteService(db).generate(payload.resume_id, payload.issue_id, payload.model_settings),
        message="改写已生成",
    )


@router.get("/rewrites/{rewrite_id}", response_model=ApiResponse, summary="查询改写结果（O-01/02）")
def get_rewrite(rewrite_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    service = RewriteService(db)
    return ok(service.get_rewrite(rewrite_id))


@router.post(
    "/rewrites/{rewrite_id}/apply",
    response_model=ApiResponse,
    summary="应用单条改写到草稿（O-03）",
)
def apply_rewrite(rewrite_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).apply(rewrite_id), message="已应用到草稿")


@router.get(
    "/resumes/{resume_id}/rewrites",
    response_model=ApiResponse,
    summary="某简历的全部改写记录",
)
def list_rewrites(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).list_rewrites(resume_id))


@router.get("/drafts/{draft_id}", response_model=ApiResponse, summary="获取草稿当前内容（O-04）")
def get_draft(draft_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).get_draft(draft_id))


@router.get(
    "/resumes/{resume_id}/draft",
    response_model=ApiResponse,
    summary="按简历获取草稿（无草稿时返回空）",
)
def get_draft_by_resume(resume_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).get_draft_by_resume(resume_id))


@router.patch(
    "/drafts/{draft_id}/fields",
    response_model=ApiResponse,
    summary="手工编辑某字段，产生新版本（O-04 / NFR-10）",
)
def edit_field(draft_id: str, payload: ManualEditRequest, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(
        RewriteService(db).manual_edit(draft_id, payload.field_name, payload.value),
        message="字段已更新",
    )


@router.get(
    "/drafts/{draft_id}/revisions",
    response_model=ApiResponse,
    summary="查询版本历史（O-03 / NFR-10）",
)
def list_revisions(draft_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).list_revisions(draft_id))


@router.post(
    "/drafts/{draft_id}/rollback",
    response_model=ApiResponse,
    summary="回滚到指定版本（O-03 / NFR-10）",
)
def rollback(draft_id: str, payload: RollbackRequest, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(
        RewriteService(db).rollback(draft_id, payload.revision_no),
        message=f"已回滚到版本 {payload.revision_no}",
    )


@router.post(
    "/drafts/{draft_id}/batch-apply",
    response_model=ApiResponse,
    summary="批量应用确定性修正，仅接受 auto_safe（O-06/07）",
)
def batch_apply(draft_id: str, payload: BatchApplyRequest, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(
        RewriteService(db).batch_apply(draft_id, payload.rewrite_ids),
        message="已批量应用",
    )


@router.post(
    "/drafts/{draft_id}/export",
    response_model=ApiResponse,
    summary="导出简历并自动触发复检（O-05）",
)
def export_draft(draft_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).export(draft_id), message="已导出并完成复检")


@router.get(
    "/drafts/{draft_id}/comparison",
    response_model=ApiResponse,
    summary="优化前后三类差异对比（O-09）",
)
def get_comparison(draft_id: str, db: Session = Depends(get_db)) -> ApiResponse:
    return ok(RewriteService(db).comparison(draft_id))


@router.post(
    "/model-settings/test",
    response_model=ApiResponse,
    summary="测试用户自带模型的连通性（不产生任何业务数据）",
)
def test_model_connection(payload: ModelSettings) -> ApiResponse:
    """连接自检：只发一个 max_tokens=1 的最小请求，不触碰简历、草稿与诊断。

    配置不成立 → 6008；连通性 / 鉴权问题 → 同样 6008，但保留具体原因供用户排查。
    该路由不需要数据库，因此不依赖 get_db。
    """
    try:
        engine = build_engine(
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except ValueError as exc:
        raise BizError(ErrorCode.MODEL_CONFIG_INVALID, str(exc)) from exc

    available, detail = engine.ping()
    if not available:
        raise BizError(ErrorCode.MODEL_CONFIG_INVALID, detail)
    return ok({"available": True, "model": payload.model, "detail": detail}, message=detail)
