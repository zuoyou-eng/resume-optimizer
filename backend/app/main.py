"""FastAPI 应用入口：统一响应、trace_id 贯穿、全局异常处理。"""
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.diagnoses import router as diagnoses_router
from app.api.highlights import router as highlights_router
from app.api.optimize import router as optimize_router
from app.api.resumes import router as resumes_router
from app.api.tailor import router as tailor_router
from app.config import settings
from app.database import init_db
from app.errors import BizError, ErrorCode, ERROR_MESSAGES, trace_id_var
from app.schemas import ApiResponse, fail

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="上传简历 → 结构化解析 → 三维度诊断 → 优化改写 → 导出复检"
    "（FR-01~03 + FR-04/05/06/08 + FR-10/11 + O-01~O-07/O-09）。"
    " 响应遵循统一格式 {code, message, data, trace_id}。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段；部署时收窄为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """trace_id 贯穿请求链路（设计文档 7.2），同时写入响应头便于排查。"""
    trace_id = request.headers.get("X-Trace-Id") or f"req-{uuid.uuid4().hex[:12]}"
    token = trace_id_var.set(trace_id)
    request.state.trace_id = trace_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Trace-Id"] = trace_id
    response.headers["X-Elapsed-Ms"] = str(elapsed_ms)
    trace_id_var.reset(token)
    return response


@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
    """业务错误 → 统一响应格式，便于接口测试按错误码断言。"""
    response = fail(exc.code, exc.message)
    return JSONResponse(status_code=200, content=response.model_dump())


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期错误：不泄露内部细节，按统一格式返回。"""
    response = fail(500, f"服务内部错误：{type(exc).__name__}")
    return JSONResponse(status_code=200, content=response.model_dump())


@app.on_event("startup")
def startup() -> None:
    init_db()


app.include_router(resumes_router, prefix="/api/v1")
app.include_router(diagnoses_router, prefix="/api/v1")
app.include_router(optimize_router, prefix="/api/v1")
app.include_router(highlights_router, prefix="/api/v1")
app.include_router(tailor_router, prefix="/api/v1")


@app.get("/api/v1/health", summary="健康检查")
def health() -> dict:
    return {"status": "up", "version": settings.APP_VERSION}
