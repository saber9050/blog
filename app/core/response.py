"""统一响应结构。

契约（与 Go 版逐字段一致）：

    {"code": 0, "message": "成功", "data": {...}}

其中 **`data` 为 None 时整个字段不输出**（对应 Go 的 `json:"data,omitempty"`）。
前端有 `if (res.data)` 这类判断，返回 `"data": null` 和「没有 data 字段」
在 JS 里虽然都判 false，但 Go 版就是缺省，这里保持一致。
"""

from typing import Any, Generic, TypeVar

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.errors import BizError, ErrorCode

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应外壳。

    只用于生成 OpenAPI 文档与类型提示；实际返回走 `ResponseBuilder`，
    因为它需要用 `exclude_none` 做字段省略。
    """

    code: int = 0
    message: str = "成功"
    data: T | None = None


class PageMeta(BaseModel):
    """通用分页信息。

    ⚠️ 字段名是 `page_size`（下划线）。
    后台用户列表用的是 `pageSize`（驼峰），那是历史遗留，不要统一。
    """

    total: int
    page: int
    page_size: int


class ResponseBuilder:
    """响应构造器。

    所有 controller **必须**通过它返回，禁止直接 `return {...}`：
    直接返回 dict 会绕过统一的 code/message 包装，前端解析时就崩了。
    """

    @staticmethod
    def ok(data: Any = None, message: str = "成功") -> JSONResponse:
        """构造成功响应。

        Args:
            data: 业务数据。传 None 时响应体里不含 `data` 字段。
            message: 提示文案，默认「成功」。

        Returns:
            HTTP 200 的 JSONResponse。
        """
        payload: dict[str, Any] = {"code": int(ErrorCode.SUCCESS), "message": message}
        if data is not None:
            # jsonable_encoder 负责把 datetime / Pydantic 模型 / ORM 对象
            # 转成可 JSON 序列化的结构
            payload["data"] = jsonable_encoder(data)
        return JSONResponse(status_code=200, content=payload)

    @staticmethod
    def fail(error: BizError) -> JSONResponse:
        """构造业务失败响应。

        注意没有 `data` 字段 —— 与 Go 版的 `Response{Code, Message}` 一致。

        Args:
            error: 业务异常。

        Returns:
            HTTP 状态码由 `error.http_status` 决定。
        """
        return JSONResponse(
            status_code=error.http_status,
            content={"code": int(error.code), "message": error.message},
        )

    @staticmethod
    def paginated(
        items: list[Any],
        total: int,
        page: int,
        page_size: int,
        message: str = "成功",
    ) -> JSONResponse:
        """构造分页成功响应。

        结构固定为 `{list, total, page, page_size}`，
        与 Go 的 `ArticleListResponse` / `CommentListResponse` 一致。

        Args:
            items: 当前页数据。
            total: 总条数。
            page: 当前页码（从 1 开始）。
            page_size: 每页条数。
            message: 提示文案。
        """
        return ResponseBuilder.ok(
            {
                "list": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
            message=message,
        )
