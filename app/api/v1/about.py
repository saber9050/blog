"""关于页接口（2 条）。

注意更新接口的路径是 `PUT /api/v1/about`，**不是** `/admin/about` ——
前端已按这个地址调用，本轮不改。
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_about_service, require_admin
from app.core.response import ResponseBuilder
from app.schemas.about import AboutUpdateRequest
from app.services.about_service import AboutService


class AboutController:
    """关于页。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(tags=["关于"])
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。"""
        r = self.router
        r.add_api_route("/about", self.get_about, methods=["GET"], summary="读取关于页")
        r.add_api_route(
            "/about",
            self.update_about,
            methods=["PUT"],
            summary="更新关于页",
            # 单条路由挂鉴权：同一个路径的 GET 是公开的
            dependencies=[Depends(require_admin)],
        )

    async def get_about(
        self,
        service: AboutService = Depends(get_about_service),
    ):
        """读取关于页。空库时文字字段返回 `""`。"""
        result = await service.get()
        return ResponseBuilder.ok(result)

    async def update_about(
        self,
        req: AboutUpdateRequest,
        service: AboutService = Depends(get_about_service),
    ):
        """更新关于页（部分更新）。"""
        await service.update(req)
        return ResponseBuilder.ok(None)
