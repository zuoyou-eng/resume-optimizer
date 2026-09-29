"""O-08 定制版本生成 API 路由。

设计文档 7.1 接口清单的增量扩展（原表未列 O-08 接口）：POST /api/v1/tailors。
与 rewrites 同风格——POST + 请求体携带业务标识，风险与守恒校验全部在服务端。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ApiResponse, TailorRequest, ok
from app.services.tailor_service import TailorService

router = APIRouter(tags=["optimize"])


@router.post(
    "/tailors",
    response_model=ApiResponse,
    summary="依据岗位匹配结果生成定制草稿版本（O-08，只重排不新增事实）",
)
def create_tailored_version(payload: TailorRequest, db: Session = Depends(get_db)) -> ApiResponse:
    data = TailorService(db).tailor(payload.resume_id, payload.jd_id)
    message = "定制版本已生成" if data.get("changed") else "当前顺序已贴合该岗位"
    return ok(data, message=message)
