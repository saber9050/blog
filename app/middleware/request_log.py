"""请求日志中间件。

只记「谁在什么时候请求了什么、耗时多少、结果如何」，
**不记请求体和响应体**：

- 登录、注册接口的请求体里有密码
- 文章正文可能有几万字，全记下来日志会爆

需要排查具体请求内容时，临时在本地打开 body 日志，别带上生产。
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from loguru import logger


def register_request_log(app: FastAPI) -> None:
    """注册请求日志中间件。

    Args:
        app: FastAPI 实例。
    """

    @app.middleware("http")
    async def log_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """记录每个请求的处理耗时与状态码。

        实现说明：用 `@app.middleware("http")` 而不是 `BaseHTTPMiddleware`，
        前者是纯 ASGI 中间件，少了请求/响应的二次封装，开销更小。
        """
        start = time.perf_counter()
        client = request.client.host if request.client else "-"

        try:
            response = await call_next(request)
        except Exception:
            # 异常已经由全局处理器记录，这里补一条「请求失败」上下文，
            # 方便把耗时和异常对应起来
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "{} {} | 500 | {:.1f}ms | client={}",
                request.method,
                request.url.path,
                elapsed_ms,
                client,
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        # 4xx 用 warning、5xx 用 error、其余 info，方便日志级别过滤
        level = "INFO"
        if response.status_code >= 500:
            level = "ERROR"
        elif response.status_code >= 400:
            level = "WARNING"

        logger.log(
            level,
            "{} {} | {} | {:.1f}ms | client={}",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            client,
        )
        return response
