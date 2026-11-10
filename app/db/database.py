"""数据库连接管理。

一个类管住 async engine 的创建与销毁，业务代码不直接碰 `create_async_engine`。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings


class Database:
    """异步数据库句柄。

    只做三件事：建 engine、发 session、关连接池。
    不含任何业务查询 —— 那些在 repository 层。
    """

    def __init__(self, settings: Settings) -> None:
        """创建 engine 与 session 工厂。

        Args:
            settings: 全局配置。
        """
        self._settings = settings
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            # ---- 连接池 ----
            pool_size=settings.database.mysql.pool_size,
            max_overflow=settings.database.mysql.max_overflow,
            # MySQL 默认 wait_timeout 是 8 小时，池里空闲超过这个时间的连接
            # 会被服务端单方面关闭，下次取出时报 "MySQL server has gone away"。
            # 主动每小时回收一次，避免拿到死连接。
            pool_recycle=3600,
            # 每次取连接前 ping 一次。比 pool_recycle 更保险，代价是每请求多一次
            # 轻量往返（MySQL 的 ping 很便宜，值得）。
            pool_pre_ping=True,
            # ---- 隔离级别 ----
            # MySQL 默认 REPEATABLE READ，会带来「同一事务内反复读到旧快照」的现象。
            # 旧 Go 版用的是 PostgreSQL 的 READ COMMITTED，这里显式降级保持行为一致。
            isolation_level="READ COMMITTED",
            # ---- 其它 ----
            echo=settings.database.mysql.echo,
            # 建表/迁移时的 DDL 用不到事务，但连接参数要统一时区，
            # 否则 DATETIME 的读写会差 8 小时
            connect_args={"init_command": "SET time_zone='+08:00'"},
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            # 提交后不过期对象：否则 model 层拿到对象后一访问属性就触发
            # 一次隐式查询（甚至在 session 关闭后报 DetachedInstanceError）
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """暴露 engine，供 Alembic 与健康检查使用。"""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """暴露 session 工厂，供 repository 在需要自己控制事务时使用。"""
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """获取一个 session 的上下文管理器。

        用于脚本 / 后台任务这类没有 FastAPI 依赖注入的场景。
        Web 请求请走 `app.core.deps.get_db`。

        用法：

            async with db.session() as s:
                await s.execute(...)
        """
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def dispose(self) -> None:
        """关闭连接池。

        应用 shutdown 时调用，否则进程退出前会有一堆
        「连接未归还」的警告。
        """
        await self._engine.dispose()


class NullPoolDatabase(Database):
    """不走连接池的数据库句柄。

    给 Alembic 迁移和集成测试用：迁移是一次性任务，用完就退出，
    连接池反而会让进程挂住不退出（asyncpg/asyncmy 的空闲连接会保活）。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=settings.database.mysql.echo,
            connect_args={"init_command": "SET time_zone='+08:00'"},
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
