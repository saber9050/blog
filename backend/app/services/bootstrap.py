"""启动引导。

目前只有一件事：保证库里至少有一个管理员。

为什么需要它：新库建好是空的，没有任何账号能进后台。
Go 版本是手工在数据库里插一条 `role_id=1` 的记录，重写时把这个步骤自动化 ——
部署到新环境不该需要「连上 MySQL 手写 INSERT」这种操作。
"""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import PasswordHasher
from app.db.models import User


class AdminBootstrapper:
    """默认管理员初始化。

    幂等：库里已经有管理员就什么都不做，重复启动不会插第二条。
    """

    def __init__(self, session: AsyncSession, hasher: PasswordHasher, settings: Settings) -> None:
        """初始化。

        Args:
            session: 数据库会话（由调用方管理事务）。
            hasher: 密码哈希器。
            settings: 取 `admin` 分组。
        """
        self._session = session
        self._hasher = hasher
        self._settings = settings

    async def ensure_admin(self) -> None:
        """确保存在一个启用的管理员。

        - `admin.enabled=false`：直接跳过（用户可能想完全手工管理）
        - 已有 `role_id=1` 的用户：跳过
        - 否则用配置里的账号密码创建

        创建失败不抛异常：管理员初始化失败不该让整个服务起不来，
        用户还能通过昵称注册普通账号，只是进不了后台。
        """
        admin_cfg = self._settings.admin
        if not admin_cfg.enabled:
            logger.info("admin.enabled=false，跳过默认管理员初始化")
            return

        try:
            existing = await self._session.execute(
                select(User.id).where(User.role_id == 1).limit(1)
            )
            if existing.scalar() is not None:
                logger.info("已存在管理员账号，跳过初始化")
                return

            account = admin_cfg.account
            user = User(
                user_name="管理员",
                account=account,
                password_hash=self._hasher.hash(admin_cfg.password.get_secret_value()),
                status=1,
                role_id=1,
            )
            self._session.add(user)
            await self._session.commit()
            # 密码只在这一行日志里出现过一次，且是配置里的初始值，
            # 不打印密码本身，避免日志泄露
            logger.warning("已创建默认管理员 account={}（请尽快登录后台修改密码）", account)
        except Exception as exc:  # noqa: BLE001 - 启动引导失败不能阻断服务
            await self._session.rollback()
            logger.error("默认管理员初始化失败：{}: {}", type(exc).__name__, exc)
