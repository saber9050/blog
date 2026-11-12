"""分类与标签的公开接口（前台 4 条）。

都不需要登录：首页、文章筛选、标签云都用这几个接口。
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_category_service, get_tag_service
from app.core.response import ResponseBuilder
from app.schemas.taxonomy import CountResponse
from app.services.taxonomy.category_service import CategoryService
from app.services.taxonomy.tag_service import TagService


class TaxonomyPublicController:
    """分类 / 标签的公开读接口。

    一个 controller 同时挂两个资源：它们共用「列表面板」这一个概念，
    拆成两个类反而要维护两份几乎相同的路由注册代码。
    """

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(tags=["分类标签"])
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        `/count` 这类静态路径写在资源路径之后不影响匹配（没有 `{id}`），
        但保持「具体路径优先」的书写习惯，将来加 `{id}` 时不会踩坑。
        """
        r = self.router
        r.add_api_route("/categories", self.list_categories, methods=["GET"], summary="分类列表")
        r.add_api_route(
            "/categories/count", self.count_categories, methods=["GET"], summary="分类数量"
        )
        r.add_api_route("/tags", self.list_tags, methods=["GET"], summary="标签列表")
        r.add_api_route("/tags/count", self.count_tags, methods=["GET"], summary="标签数量")

    async def list_categories(
        self,
        service: CategoryService = Depends(get_category_service),
    ):
        """启用的分类列表。

        `data` 直接是数组，**不是分页对象** —— 前端 `res.data.map(...)` 用的。
        """
        items = await service.list_public()
        return ResponseBuilder.ok(items)

    async def count_categories(
        self,
        service: CategoryService = Depends(get_category_service),
    ):
        """启用分类数量。"""
        count = await service.count_enabled()
        return ResponseBuilder.ok(CountResponse(count=count))

    async def list_tags(
        self,
        service: TagService = Depends(get_tag_service),
    ):
        """启用的标签列表。"""
        items = await service.list_public()
        return ResponseBuilder.ok(items)

    async def count_tags(
        self,
        service: TagService = Depends(get_tag_service),
    ):
        """启用标签数量。"""
        count = await service.count_enabled()
        return ResponseBuilder.ok(CountResponse(count=count))
