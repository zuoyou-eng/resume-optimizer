"""统一错误码与业务异常。

错误码与《系统设计文档》7.3 节对齐：
  1001 文件类型不支持 / 1002 文件过大 / 1003 文件内容为空或无法识别
  2001 解析失败 / 2002 诊断任务不存在
  2003 简历不存在 —— 对设计文档错误码表的增量扩展（初始版本新增场景，已在 README 说明）
  2004/2005 岗位描述相关 —— V1.1 三维度诊断阶段新增（JD 不存在 / 内容过少）
  6001-6006 优化模块 —— V1.1 改写/草稿/回滚/对比阶段新增（见设计文档 7.3）
"""
from contextvars import ContextVar

# 贯穿请求链路的 trace_id（设计文档 7.2：日志与各模块耗时均以此关联）
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


class ErrorCode:
    OK = 0
    FILE_TYPE_NOT_SUPPORTED = 1001
    FILE_TOO_LARGE = 1002
    FILE_EMPTY = 1003
    PARSE_FAILED = 2001
    DIAGNOSIS_NOT_FOUND = 2002
    RESUME_NOT_FOUND = 2003  # 增量扩展：查询/删除不存在的简历
    JOB_DESC_NOT_FOUND = 2004  # 增量扩展：岗位描述不存在（FR-08）
    JD_TOO_SHORT = 2005  # 增量扩展：岗位描述内容过少，无法提取关键要求
    # ---- 优化模块（设计文档 7.3，V1.1）----
    REWRITE_TARGET_NOT_FOUND = 6001
    REWRITE_FACT_CHECK_FAILED = 6002
    REWRITE_NOT_AUTO_SAFE = 6003  # 对 needs_review 的改写调用批量应用
    REVISION_NOT_FOUND = 6004
    DRAFT_VERSION_CONFLICT = 6005
    COMPARISON_NOT_COMPARABLE = 6006
    TAILOR_NO_MATCH = 6007  # 增量扩展：定制版本（O-08）缺少针对该岗位的 match 诊断
    MODEL_CONFIG_INVALID = 6008  # 增量扩展：用户自带模型配置不合法（地址/模型名）


ERROR_MESSAGES: dict[int, str] = {
    ErrorCode.OK: "ok",
    ErrorCode.FILE_TYPE_NOT_SUPPORTED: "文件类型不支持，仅支持 PDF / Word / 纯文本 / 图片",
    ErrorCode.FILE_TOO_LARGE: "文件过大，超出大小限制",
    ErrorCode.FILE_EMPTY: "文件内容为空或无法识别",
    ErrorCode.PARSE_FAILED: "解析失败，文档结构无法识别",
    ErrorCode.DIAGNOSIS_NOT_FOUND: "诊断任务不存在",
    ErrorCode.RESUME_NOT_FOUND: "简历不存在或已被删除",
    ErrorCode.JOB_DESC_NOT_FOUND: "岗位描述不存在",
    ErrorCode.JD_TOO_SHORT: "岗位描述内容过少，无法提取关键要求",
    # ---- 优化模块（设计文档 7.3 错误码表 V1.1）----
    ErrorCode.REWRITE_TARGET_NOT_FOUND: "改写目标不存在：问题项已失效或目标字段已被删除",
    ErrorCode.REWRITE_FACT_CHECK_FAILED: "改写事实校验失败：改写会改变或新增原文没有的事实",
    ErrorCode.REWRITE_NOT_AUTO_SAFE: "该改写需人工确认，不能自动应用",
    ErrorCode.REVISION_NOT_FOUND: "版本不存在或已被清理",
    ErrorCode.DRAFT_VERSION_CONFLICT: "草稿版本冲突：请刷新后重试",
    ErrorCode.COMPARISON_NOT_COMPARABLE: "对比数据不可比：前后解析器或规则版本不一致",
    ErrorCode.TAILOR_NO_MATCH: "该简历尚未针对此岗位诊断，无法生成定制版本",
    ErrorCode.MODEL_CONFIG_INVALID: "模型配置无效：接口地址需为 http(s):// 开头，且需填写模型名称",
}


class BizError(Exception):
    """业务异常：由全局异常处理器转换为统一响应格式。"""

    def __init__(self, code: int, message: str | None = None):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "未知错误")
        super().__init__(self.message)
