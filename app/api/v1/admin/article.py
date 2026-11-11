"""文章后台接口（6 条）。

路由顺序硬要求：`PUT /articles/transfer` 必须注册在 `PUT /articles/{article_id}`
之前，否则 `transfer` 会被当成 ID，`int("transfer")` 失败 → 422。
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.deps import (
    CurrentUser,
    get_admin_article_service,
    get_current_user,
    require_admin,
)
from app.core.response import ResponseBuilder
from app.schemas.article import (
    AdminArticleQuery,
    ArticleCreateRequest,
    ArticleIdResponse,
    ArticleTransferRequest,
    ArticleUpdateRequest,
    TransferCountResponse,
    UploadResponse,
)
from app.services.article.admin_article_service import AdminArticleService


def _parse_query(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    status: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    keyword: str = Query(default=""),
) -> AdminArticleQuery:
    """把 query 参数收成对象。

    注意 `tag_id` 是**单个** —— 前台是逗号分隔的 `tag_ids`，两者不同。
    """
    return AdminArticleQuery(
        page=page,
        page_size=page_size,
        status=status,
        category_id=category_id,
        tag_id=tag_id,
        keyword=keyword,
    )


class AdminArticleController:
    """后台文章管理。整组要求管理员。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(
            prefix="/admin",
            tags=["后台-文章"],
            dependencies=[Depends(require_admin)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        ⚠️ `PUT /articles/transfer` 必须在 `PUT /articles/{article_id}` 之前。
        """
        r = self.router
        r.add_api_route("/articles", self.list_articles, methods=["GET"], summary="后台文章列表")
        r.add_api_route("/articles", self.create_article, methods=["POST"], summary="新建文章")
        # ---- 静态路径（必须在 {article_id} 之前）----
        r.add_api_route(
            "/articles/transfer", self.transfer_category, methods=["PUT"], summary="批量转移分类"
        )
        # ---- 动态路径 ----
        r.add_api_route(
            "/articles/{article_id}", self.update_article, methods=["PUT"], summary="更新文章"
        )
        r.add_api_route(
            "/articles/{article_id}", self.delete_article, methods=["DELETE"], summary="删除文章"
        )
        # 上传接口在 /admin/upload，不带 /articles 前缀
        r.add_api_route("/upload", self.upload_image, methods=["POST"], summary="上传图片")

    async def list_articles(
        self,
        query: AdminArticleQuery = Depends(_parse_query),
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """后台文章列表（含草稿）。"""
        result = await service.admin_list(query)
        return ResponseBuilder.ok(result)

    async def create_article(
        self,
        req: ArticleCreateRequest,
        user: CurrentUser = Depends(get_current_user),
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """新建文章。作者取当前管理员，不接受前端传 `user_id`。"""
        new_id = await service.create(req, author_id=user.user_id)
        return ResponseBuilder.ok(ArticleIdResponse(id=new_id))

    async def update_article(
        self,
        article_id: int,
        req: ArticleUpdateRequest,
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """更新文章。只改传了的字段。"""
        await service.update(article_id, req)
        return ResponseBuilder.ok(None)

    async def delete_article(
        self,
        article_id: int,
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """删除文章（软删），同时清图片、软删评论、清标签关联。"""
        await service.delete(article_id)
        return ResponseBuilder.ok(None)

    async def transfer_category(
        self,
        req: ArticleTransferRequest,
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """把某个分类下的文章全部转到另一个分类。删分类前用它腾空。"""
        count = await service.transfer_category(req.from_type_id, req.to_type_id)
        return ResponseBuilder.ok(TransferCountResponse(count=count))

    async def upload_image(
        self,
        file: UploadFile = File(description="图片文件"),
        service: AdminArticleService = Depends(get_admin_article_service),
    ):
        """上传正文图片，返回完整 URL（前端塞进 Markdown）。"""
        url = await service.upload_image(file)
        return ResponseBuilder.ok(UploadResponse(url=url))
