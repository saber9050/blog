"""Alembic 运行环境。

关键点：

1. **连接串从 `Settings` 读**，不读 `alembic.ini`，避免两处配置漂移。
2. 用 **async engine**：项目连接串是 `mysql+asyncmy://`，
   同步驱动（pymysql）没装，直接跑同步迁移会失败。
3. 元数据从 `app.db.models.ALL_MODELS` 取，新增模型后自动进入
   autogenerate 的比对范围。
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from app.core.config import get_settings
from app.db import models as _models  # noqa: F401

# 必须 import 模型包，否则 Base.metadata 是空的，
# autogenerate 会认为「所有表都应该被删除」
from app.db.base import Base

config = context.config

# 只有在有 alembic.ini 的情况下才配置日志（脚本调用时可能没有）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用 Settings 里的连接串覆盖 ini 里的空值
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连库。

    用于「先 review SQL 再执行」或者在没有数据库的环境里产出建表脚本：

        alembic upgrade head --sql > schema.sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 让 MySQL 的列注释也能写进 DDL
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """在已建立的同步连接上执行迁移。

    Alembic 的迁移逻辑本身是同步的，需要在异步连接里用 `run_sync` 包一层。

    Args:
        connection: 由 async engine 提供的同步连接。
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # 类型变化也纳入 diff（比如 varchar(50) → varchar(100)）
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：连库执行迁移。

    `poolclass=NullPool`：迁移是一次性任务，用完就退出，
    连接池会让进程挂住不退出。
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
