"""后台评论管理（3 条）。"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_comment_service, require_admin
from app.core.response import ResponseBuilder
from app.schemas.comment import AdminCommentQuery, BatchDeleteRequest, BatchDeleteResponse
from app.services.comment_service import CommentService


def _parse_query(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    article_title: str = Query(default=""),
    user_name: str = Query(default=""),
    start_time: str = Query(default=""),
    end_time: str = Query(default=""),
) -> AdminCommentQuery:
    """把 query 参数收成对象。"""
    return AdminCommentQuery(
        page=page,
        page_size=page_size,
        article_title=article_title,
        user_name=user_name,
        start_time=start_time,
        end_time=end_time,
    )


class AdminCommentController:
    """后台评论管理。整组要求管理员。"""

    def __init__(self) -> None:
        """构造并注册路由。

        ⚠️ 批量删除 `DELETE ""` 与单条 `DELETE "/{comment_id}"` 不冲突
        （路径段数不同），但按「具体在前」的习惯，把无参数的放前面。
        """
        self.router = APIRouter(
            prefix="/admin/comments",
            tags=["后台-评论"],
            dependencies=[Depends(require_admin)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。"""
        r = self.router
        r.add_api_route("", self.list_comments, methods=["GET"], summary="评论列表")
        r.add_api_route("", self.batch_delete, methods=["DELETE"], summary="批量删除")
        r.add_api_route(
            "/{comment_id}", self.delete_comment, methods=["DELETE"], summary="删除单条"
        )

    async def list_comments(
        self,
        query: AdminCommentQuery = Depends(_parse_query),
        service: CommentService = Depends(get_comment_service),
    ):
        """评论列表。只返回未删除的（与前台相反）。"""
        result = await service.admin_list(query)
        return ResponseBuilder.ok(result)

    async def delete_comment(
        self,
        comment_id: int,
        service: CommentService = Depends(get_comment_service),
    ):
        """删除单条（级联删回复）。"""
        await service.admin_delete(comment_id)
        return ResponseBuilder.ok(None)

    async def batch_delete(
        self,
        req: BatchDeleteRequest,
        service: CommentService = Depends(get_comment_service),
    ):
        """批量删除。空数组返回 count=0，不报错。"""
        count = await service.admin_batch_delete(req.ids)
        return ResponseBuilder.ok(BatchDeleteResponse(count=count))
