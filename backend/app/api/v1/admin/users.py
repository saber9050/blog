"""后台用户管理（4 条）。

与前台 `UserController` 分成两个类：鉴权级别、参数来源、响应字段都不同
（前台看自己，后台看别人），混在一起每个方法开头都得写 `if is_admin`。
"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, get_user_service, require_admin
from app.core.response import ResponseBuilder
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminUpdateUserRequest,
    AdminUserQuery,
)
from app.services.user.user_service import UserService


def _parse_query(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页条数"),
    keyword: str = Query(default="", description="昵称或账号模糊匹配"),
    status: int | None = Query(default=None, description="1 启用 / 0 禁用"),
    start_time: str = Query(default="", description="注册时间起 YYYY-MM-DD"),
    end_time: str = Query(default="", description="注册时间止 YYYY-MM-DD"),
) -> AdminUserQuery:
    """把散装的 query 参数收成一个对象。

    为什么不用 `Depends()` 直接把 Pydantic 模型当查询参数：
    FastAPI 对「模型作为 query」的支持依赖版本，这里手工转换一次更可控，
    也让参数校验规则（ge / le）集中在签名上。
    """
    return AdminUserQuery(
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        start_time=start_time,
        end_time=end_time,
    )


class AdminUserController:
    """后台用户管理。整组要求 `role_id == 1`。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(
            prefix="/admin/users",
            tags=["后台-用户"],
            # 整组挂鉴权：漏写一个依赖就是越权漏洞，挂在 router 上一次搞定
            dependencies=[Depends(require_admin)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        本组没有静态路径与 `{id}` 的冲突（只有 `PUT/DELETE /{id}`），
        顺序不影响匹配。
        """
        r = self.router
        r.add_api_route("", self.list_users, methods=["GET"], summary="用户列表")
        r.add_api_route("", self.create_user, methods=["POST"], summary="创建用户")
        r.add_api_route("/{user_id}", self.update_status, methods=["PUT"], summary="启用/禁用")
        r.add_api_route("/{user_id}", self.delete_user, methods=["DELETE"], summary="删除用户")

    async def list_users(
        self,
        query: AdminUserQuery = Depends(_parse_query),
        service: UserService = Depends(get_user_service),
    ):
        """用户列表。只返回普通用户（`role_id=0`）。"""
        result = await service.admin_list(query)
        return ResponseBuilder.ok(result)

    async def create_user(
        self,
        req: AdminCreateUserRequest,
        service: UserService = Depends(get_user_service),
    ):
        """创建用户。返回 `{id}`。"""
        new_id = await service.admin_create(req)
        return ResponseBuilder.ok(AdminCreateUserResponse(id=new_id))

    async def update_status(
        self,
        user_id: int,
        req: AdminUpdateUserRequest,
        current: CurrentUser = Depends(require_admin),
        service: UserService = Depends(get_user_service),
    ):
        """启用 / 禁用。不能改自己。"""
        await service.admin_update_status(user_id, req.status, operator_id=current.user_id)
        return ResponseBuilder.ok(None)

    async def delete_user(
        self,
        user_id: int,
        current: CurrentUser = Depends(require_admin),
        service: UserService = Depends(get_user_service),
    ):
        """软删除。不能删自己。"""
        await service.admin_delete(user_id, operator_id=current.user_id)
        return ResponseBuilder.ok(None)
