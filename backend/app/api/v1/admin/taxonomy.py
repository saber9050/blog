"""分类与标签的后台接口（8 条）。

两类资源的 CRUD 形状完全一致，差异都在 service 的钩子里，
所以这里每个方法只做「解析 → 调 service → 包响应」。
"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_category_service, get_tag_service, require_admin
from app.core.response import ResponseBuilder
from app.schemas.taxonomy import (
    TaxonomyCreateRequest,
    TaxonomyIdResponse,
    TaxonomyQuery,
    TaxonomyUpdateRequest,
)
from app.services.taxonomy.category_service import CategoryService
from app.services.taxonomy.tag_service import TagService


def _parse_query(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: int | None = Query(default=None),
    keyword: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
) -> TaxonomyQuery:
    """把散装 query 参数收成对象（与后台用户列表同样的做法）。"""
    return TaxonomyQuery(
        page=page,
        page_size=page_size,
        status=status,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
    )


class AdminTaxonomyController:
    """后台分类 / 标签管理。整组要求管理员。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(
            prefix="/admin",
            tags=["后台-分类标签"],
            dependencies=[Depends(require_admin)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        `/categories` 与 `/categories/{id}` 的方法不重叠
        （列表是 GET，改删是 PUT/DELETE），所以没有匹配顺序问题。
        """
        r = self.router
        r.add_api_route(
            "/categories", self.list_categories, methods=["GET"], summary="后台分类列表"
        )
        r.add_api_route("/categories", self.create_category, methods=["POST"], summary="新建分类")
        r.add_api_route(
            "/categories/{category_id}", self.update_category, methods=["PUT"], summary="更新分类"
        )
        r.add_api_route(
            "/categories/{category_id}",
            self.delete_category,
            methods=["DELETE"],
            summary="删除分类",
        )
        r.add_api_route("/tags", self.list_tags, methods=["GET"], summary="后台标签列表")
        r.add_api_route("/tags", self.create_tag, methods=["POST"], summary="新建标签")
        r.add_api_route("/tags/{tag_id}", self.update_tag, methods=["PUT"], summary="更新标签")
        r.add_api_route("/tags/{tag_id}", self.delete_tag, methods=["DELETE"], summary="删除标签")

    # ============================================================
    # 分类
    # ============================================================

    async def list_categories(
        self,
        query: TaxonomyQuery = Depends(_parse_query),
        service: CategoryService = Depends(get_category_service),
    ):
        """分类列表。分页键是下划线 `page_size`（与后台用户列表的驼峰不同）。"""
        result = await service.list_admin(query)
        return ResponseBuilder.ok(result)

    async def create_category(
        self,
        req: TaxonomyCreateRequest,
        service: CategoryService = Depends(get_category_service),
    ):
        """新建分类。"""
        new_id = await service.create(req)
        return ResponseBuilder.ok(TaxonomyIdResponse(id=new_id))

    async def update_category(
        self,
        category_id: int,
        req: TaxonomyUpdateRequest,
        service: CategoryService = Depends(get_category_service),
    ):
        """更新分类。"""
        await service.update(category_id, req)
        return ResponseBuilder.ok(None)

    async def delete_category(
        self,
        category_id: int,
        service: CategoryService = Depends(get_category_service),
    ):
        """删除分类。分类下有文章时拒绝。"""
        await service.delete(category_id)
        return ResponseBuilder.ok(None)

    # ============================================================
    # 标签
    # ============================================================

    async def list_tags(
        self,
        query: TaxonomyQuery = Depends(_parse_query),
        service: TagService = Depends(get_tag_service),
    ):
        """标签列表。"""
        result = await service.list_admin(query)
        return ResponseBuilder.ok(result)

    async def create_tag(
        self,
        req: TaxonomyCreateRequest,
        service: TagService = Depends(get_tag_service),
    ):
        """新建标签。"""
        new_id = await service.create(req)
        return ResponseBuilder.ok(TaxonomyIdResponse(id=new_id))

    async def update_tag(
        self,
        tag_id: int,
        req: TaxonomyUpdateRequest,
        service: TagService = Depends(get_tag_service),
    ):
        """更新标签。"""
        await service.update(tag_id, req)
        return ResponseBuilder.ok(None)

    async def delete_tag(
        self,
        tag_id: int,
        service: TagService = Depends(get_tag_service),
    ):
        """删除标签。有文章关联也允许，会先清关联。"""
        await service.delete(tag_id)
        return ResponseBuilder.ok(None)
