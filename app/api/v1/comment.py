"""评论前台接口（4 条）。

挂在 `/articles/{article_id}/comments` 下 —— 路径前缀与文章共用，
但注册在独立的 router 上：评论的业务规则、分页上限都与文章不同，
塞进 `ArticleController` 只会让那个类越来越胖。
"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, get_comment_service, get_current_user
from app.core.response import ResponseBuilder
from app.schemas.comment import CommentCreateRequest
from app.services.comment_service import CommentService


class CommentController:
    """评论的公开读 + 登录写。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(prefix="/articles", tags=["评论"])
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        这里的路径都比文章模块的 `/{article_id}` 多一段，
        不会互相抢匹配，但仍按「具体在前」的习惯书写。
        """
        r = self.router
        r.add_api_route(
            "/{article_id}/comments", self.list_comments, methods=["GET"], summary="一级评论列表"
        )
        r.add_api_route(
            "/{article_id}/comments/{comment_id}/replies",
            self.list_replies,
            methods=["GET"],
            summary="二级回复列表",
        )
        r.add_api_route(
            "/{article_id}/comments", self.create_comment, methods=["POST"], summary="发表评论"
        )
        r.add_api_route(
            "/{article_id}/comments/{comment_id}",
            self.delete_comment,
            methods=["DELETE"],
            summary="删除评论",
        )

    async def list_comments(
        self,
        article_id: int,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1),
        service: CommentService = Depends(get_comment_service),
    ):
        """一级评论列表。

        `page_size` 上限 50 —— 在 service 层截断，不在这里报错。
        文章不存在时返回空列表（前端不用处理 404）。
        """
        result = await service.list_top_level(article_id, page, page_size)
        return ResponseBuilder.ok(result)

    async def list_replies(
        self,
        article_id: int,
        comment_id: int,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1),
        service: CommentService = Depends(get_comment_service),
    ):
        """二级回复列表。默认 10 条、上限 30（与一级列表不同）。"""
        result = await service.list_replies(article_id, comment_id, page, page_size)
        return ResponseBuilder.ok(result)

    async def create_comment(
        self,
        article_id: int,
        req: CommentCreateRequest,
        user: CurrentUser = Depends(get_current_user),
        service: CommentService = Depends(get_comment_service),
    ):
        """发表评论或回复。返回新建的评论对象。"""
        item = await service.create(article_id, user.user_id, req)
        return ResponseBuilder.ok(item)

    async def delete_comment(
        self,
        article_id: int,
        comment_id: int,
        user: CurrentUser = Depends(get_current_user),
        service: CommentService = Depends(get_comment_service),
    ):
        """删除评论。作者本人或管理员可删，一级评论会级联删回复。"""
        await service.delete(article_id, comment_id, user_id=user.user_id, is_admin=user.is_admin)
        return ResponseBuilder.ok(None)
