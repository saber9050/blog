"""模型配置仓储。

`api_key` 在库里是 Fernet 密文，加解密由 service 层的 `CryptoBox` 负责 ——
仓储只存**它拿到的字符串**，不关心是明文还是密文。这样单测塞明文也能跑通。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIModelConfig


class LLMConfigRepository:
    """`ai_model_configs` 表读写。"""

    def __init__(self, session: AsyncSession) -> None:
        """初始化。

        Args:
            session: 数据库会话。
        """
        self._session = session

    async def list_all(self) -> list[AIModelConfig]:
        """全部配置，配置条数极少，不分页。"""
        stmt = select(AIModelConfig).order_by(AIModelConfig.id.asc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_by_id(self, config_id: int) -> AIModelConfig | None:
        """按 ID 查。"""
        stmt = select(AIModelConfig).where(AIModelConfig.id == config_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, config: AIModelConfig) -> int:
        """插入，返回自增 ID。

        **不 commit**：事务边界归 service（新建前要先测连接，测通了才写库）。
        """
        self._session.add(config)
        await self._session.flush()
        return int(config.id)

    async def update_fields(self, config_id: int, **fields: object) -> None:
        """局部更新。"""
        if not fields:
            return
        config = await self._session.get(AIModelConfig, config_id)
        if config is None:
            return
        for key, value in fields.items():
            setattr(config, key, value)
        await self._session.flush()

    async def delete(self, config_id: int) -> None:
        """物理删除。历史摘要存在 `articles.summary` 里，不受影响。"""
        config = await self._session.get(AIModelConfig, config_id)
        if config is not None:
            await self._session.delete(config)
            await self._session.flush()

    async def count(self) -> int:
        """配置条数，用于日志。"""
        stmt = select(func.count()).select_from(AIModelConfig)
        return int((await self._session.execute(stmt)).scalar_one())
