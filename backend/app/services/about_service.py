"""关于页业务。

数据来自两张表：`abouts`（6 个文字字段）+ `users`（管理员昵称/头像/邮箱/简介）。
前台只需要调这一个接口就能渲染整页，不用再去调 `/user/info`。
"""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsFileStorage
from app.db.base import not_deleted
from app.db.models import User
from app.repositories.about_repository import AboutRepository
from app.schemas.about import AboutResponse, AboutUpdateRequest


class AboutService:
    """关于页读写。"""

    def __init__(
        self,
        session: AsyncSession,
        repo: AboutRepository,
        storage: SupportsFileStorage,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 关于页仓储。
            storage: 对象存储（拼头像 URL）。
        """
        self._session = session
        self._repo = repo
        self._storage = storage

    async def get(self) -> AboutResponse:
        """读取关于页。

        两种情况要区分清楚：

        - `abouts` 表空但**有管理员** → 6 个文字字段返回 `""`，不报错。
          全新库第一次打开关于页就是这个场景。
        - **连管理员都没有** → 404。这时候页面没有任何可展示的主人信息。

        Raises:
            BizError: 404 资源不存在。
        """
        admin = await self._find_admin()
        if admin is None:
            raise BizError(ErrorCode.NOT_FOUND, "资源不存在")

        about = await self._repo.get_first()
        return AboutResponse(
            admin_name=admin.user_name,
            avatar_url=self._storage.public_url(admin.avatar_url or ""),
            email=admin.email or "",
            introduction=admin.introduction or "",
            tech_stack=(about.tech_stack or "") if about else "",
            my_story=(about.my_story or "") if about else "",
            why=(about.why or "") if about else "",
            interest=(about.interest or "") if about else "",
            git_hub=(about.git_hub or "") if about else "",
            csdn=(about.csdn or "") if about else "",
        )

    async def update(self, req: AboutUpdateRequest) -> None:
        """部分更新。

        只写传了的字段：`None` 表示不修改。想清空就传 `""`。

        表为空时先建一条再改 —— 否则 UPDATE 影响 0 行，用户的修改静默丢失。
        """
        # exclude_unset 只取用户真的传了的字段；
        # 但 Pydantic 的 None 也可能是「显式传了 null」，这里按「不修改」处理
        fields = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
        if not fields:
            return

        about = await self._repo.get_first()
        if about is None:
            about = await self._repo.create_empty()
            logger.info("abouts 表为空，已自动创建首条记录")

        await self._repo.update_fields(about.id, **fields)
        await self._session.commit()
        logger.info("关于页已更新 fields={}", list(fields))

    async def _find_admin(self) -> User | None:
        """取第一个管理员。

        有多条时取 id 最小的那条，行为确定。
        """
        stmt = (
            select(User)
            .where(User.role_id == 1, not_deleted(User))
            .order_by(User.id.asc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()
