"""全局异常处理。

目标只有一条：**任何异常都不能把堆栈、SQL 语句、文件路径泄露给前端**。
用户在页面上看到的永远是「服务器内部错误」，完整信息只进日志。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import BizError, ErrorCode
from app.core.response import ResponseBuilder


def register_exception_handlers(app: FastAPI) -> None:
    """把异常处理器挂到应用上。

    Args:
        app: FastAPI 实例。
    """

    @app.exception_handler(BizError)
    async def handle_biz_error(_: Request, exc: BizError) -> JSONResponse:
        """业务异常 → 统一响应。

        这类异常是**预期内**的（密码错误、资源不存在），
        只记 info 级别，不打堆栈 —— 否则日志会被正常业务错误刷屏。
        """
        logger.info("业务异常 | code={} | message={}", int(exc.code), exc.message)
        return ResponseBuilder.fail(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        """参数校验失败 → 400。

        FastAPI 默认返回 422 + 一份很长的英文错误数组，前端解析不了。
        Go 版这里统一返回 `{"code":400,"message":"请求参数错误"}`，
        保持契约一致。

        详细的字段错误只进日志，不回给前端（里面有用户输入的内容）。
        """
        logger.info("参数校验失败 | errors={}", exc.errors())
        return ResponseBuilder.fail(BizError(ErrorCode.BAD_REQUEST, "请求参数错误"))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """框架层 HTTP 异常（404 路由不存在、405 方法不允许等）。

        转成统一响应结构，避免前端拿到 `{"detail":"Not Found"}` 这种格式。
        """
        code = exc.status_code
        message = {
            404: "资源不存在",
            405: "方法不允许",
        }.get(code, str(exc.detail))
        return JSONResponse(
            status_code=code,
            content={"code": code, "message": message},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        """兜底：未预期异常 → 500。

        `logger.exception` 会带完整堆栈进日志文件，
        对外的 message 固定为「服务器内部错误」，不暴露任何内部信息。
        """
        logger.exception("未捕获异常 | type={}", type(exc).__name__)
        return ResponseBuilder.fail(BizError(ErrorCode.INTERNAL_ERROR, "服务器内部错误"))
