"""FastAPI 依赖注入。

所有「跨模块共享的东西」都从这里取：数据库会话、缓存、对象存储、当前用户。
业务代码不在构造函数里 new 这些依赖，统一走 `Depends()` —— 单测时可以整组替换。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsCache, SupportsFileStorage
from app.core.security import JWTManager
from app.db.database import Database


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """获取数据库会话。

    生命周期：请求开始创建 → 请求结束关闭。

    **不在这里自动 commit**。事务边界由 service 层显式控制：

        await self._session.commit()      # 写操作
        await self._session.rollback()    # 出错

    为什么不统一 commit：读请求也 commit 是多余往返；
    而「上传图片成功但写库失败」这类场景需要在 service 里做补偿，
    自动提交会让补偿失效。

    Yields:
        AsyncSession 实例。
    """
    db: Database = request.app.state.db
    async with db.session() as session:
        yield session


def get_cache(request: Request) -> SupportsCache:
    """获取缓存实现（Redis 或内存降级）。

    返回值声明成 Protocol 而不是具体类，业务代码只依赖能力契约。
    """
    return request.app.state.cache


def get_storage(request: Request) -> SupportsFileStorage:
    """获取对象存储。"""
    return request.app.state.storage


def get_jwt(request: Request) -> JWTManager:
    """获取 JWT 管理器。"""
    return request.app.state.jwt


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """当前登录用户。

    只从 token 里解析，**不查库**：
    access token 有效期只有 15 分钟，每个请求都查一次 users 表等于自找瓶颈。
    代价是「用户被禁用后 15 分钟内仍能操作」，这个窗口可以接受
    （Go 版也是这个行为）。
    """

    user_id: int
    username: str
    role_id: int
    # 当前会话标识，登出时用来判断「是不是新设备把我踢了」
    tid: str

    @property
    def is_admin(self) -> bool:
        """是否管理员。"""
        return self.role_id == 1


def _extract_bearer(authorization: str | None) -> str:
    """从请求头里取出 Bearer token。

    Args:
        authorization: `Authorization` 头的原始值。

    Returns:
        纯 token 字符串。

    Raises:
        BizError: 401 未提供 / 格式错误。
    """
    if not authorization:
        raise BizError(ErrorCode.UNAUTHORIZED, "请提供认证令牌")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        raise BizError(ErrorCode.UNAUTHORIZED, "令牌格式错误")
    return parts[1]


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    """解析当前登录用户，未登录抛 401。

    Args:
        request: 用于取 `app.state.jwt`。
        authorization: 请求头，由 FastAPI 注入。

    Returns:
        当前用户信息。

    Raises:
        BizError: 401 缺失、格式错误、过期或无效。
    """
    token = _extract_bearer(authorization)
    jwt_manager: JWTManager = request.app.state.jwt
    claims = jwt_manager.decode(token)
    return CurrentUser(
        user_id=claims.user_id,
        username=claims.username,
        role_id=claims.role_id,
        tid=claims.tid,
    )


async def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> CurrentUser | None:
    """可选登录。

    用于「带 token 就返回个性化数据，不带也能看」的接口，
    典型场景：文章列表/详情里的 `is_liked`。

    注意这里**吞掉所有异常**并返回 None，而不是抛 401 ——
    token 过期时首页不该变成错误页，降级成游客视图即可。
    """
    if not authorization:
        return None
    try:
        token = _extract_bearer(authorization)
        jwt_manager: JWTManager = request.app.state.jwt
        claims = jwt_manager.decode(token)
    except BizError:
        return None
    return CurrentUser(
        user_id=claims.user_id,
        username=claims.username,
        role_id=claims.role_id,
        tid=claims.tid,
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """要求管理员身份。

    依赖链：先走 `get_current_user` 校验登录，再判断角色。
    FastAPI 会自动按函数签名解析依赖。

    Raises:
        BizError: 403 非管理员。
    """
    if not user.is_admin:
        raise BizError(ErrorCode.FORBIDDEN, "禁止访问")
    return user
