"""FastAPI 依赖注入。

所有「跨模块共享的东西」都从这里取：数据库会话、缓存、对象存储、当前用户。
业务代码不在构造函数里 new 这些依赖，统一走 `Depends()` —— 单测时可以整组替换。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsCache, SupportsFileStorage
from app.core.security import JWTManager
from app.db.database import Database
from app.repositories.auth_repository import AuthRepository

if TYPE_CHECKING:  # 只给类型检查用，避免运行期循环导入
    from app.services.auth.auth_service import AuthService
    from app.services.taxonomy.category_service import CategoryService
    from app.services.taxonomy.tag_service import TagService
    from app.services.user.user_service import UserService


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


async def get_auth_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cache: SupportsCache = Depends(get_cache),
) -> "AuthService":
    """组装认证服务。

    每次请求新建对象，不做单例：这些对象本身很轻（只是持有引用），
    但 `AuthRepository` 必须绑定**当前请求的 session** ——
    做成单例就会跨请求复用连接，事务边界全乱。

    Returns:
        可直接使用的 AuthService。
    """
    # 延迟导入：deps 被几乎所有模块引用，顶层导入 auth 会形成拉长的启动链
    from app.services.auth.auth_service import AuthService
    from app.services.auth.captcha import ImageCaptchaGenerator
    from app.services.auth.mailer import EmailSender

    settings: Settings = request.app.state.settings
    return AuthService(
        session=db,
        repo=AuthRepository(db),
        cache=_build_auth_cache(settings, cache),
        captcha=ImageCaptchaGenerator(),
        mailer=EmailSender(settings),
        hasher=request.app.state.hasher,
        jwt_manager=request.app.state.jwt,
        settings=settings,
    )


async def get_user_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cache: SupportsCache = Depends(get_cache),
    storage: SupportsFileStorage = Depends(get_storage),
    auth_service: "AuthService" = Depends(get_auth_service),
) -> "UserService":
    """组装用户服务。

    `auth_service` 是注入进来的，不是自己 new：这样两者共用
    **同一个 session 和同一个缓存实例**，验证码校验与写库在同一个事务上下文里。

    方法级和 router 级的 `require_admin` 看似会跑两次，但 FastAPI 对
    同一请求内的相同依赖有缓存，实际只执行一次。

    Returns:
        可直接使用的 UserService。
    """
    from app.repositories.user_repository import UserRepository
    from app.services.auth.mailer import EmailSender
    from app.services.user.user_service import UserService

    settings: Settings = request.app.state.settings
    return UserService(
        session=db,
        repo=UserRepository(db),
        auth_service=auth_service,
        cache=_build_auth_cache(settings, cache),
        storage=storage,
        mailer=EmailSender(settings),
        hasher=request.app.state.hasher,
        jwt_manager=request.app.state.jwt,
        settings=settings,
    )


def _build_auth_cache(settings: Settings, cache: SupportsCache):
    """构造 AuthCache。

    TTL 都从配置取，避免两处写死不同的数值。
    """
    from app.services.auth.auth_cache import AuthCache

    return AuthCache(
        cache,
        captcha_ttl=settings.business.captcha_expire_seconds,
        send_limit_ttl=settings.business.captcha_send_limit_seconds,
    )


async def get_category_service(
    db: AsyncSession = Depends(get_db),
) -> "CategoryService":
    """组装分类服务。

    Returns:
        绑定当前请求 session 的 CategoryService。
    """
    from app.repositories.taxonomy.category_repository import CategoryRepository
    from app.services.taxonomy.category_service import CategoryService

    return CategoryService(session=db, repo=CategoryRepository(db))


async def get_tag_service(
    db: AsyncSession = Depends(get_db),
) -> "TagService":
    """组装标签服务。

    Returns:
        绑定当前请求 session 的 TagService。
    """
    from app.repositories.taxonomy.tag_repository import TagRepository
    from app.services.taxonomy.tag_service import TagService

    return TagService(session=db, repo=TagRepository(db))


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
