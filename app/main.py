"""应用入口。

启动链路：

    uvicorn app.main:app
      → create_app()
          → Settings()              配置缺失直接抛异常，不带病启动
          → LoggingConfigurator     日志先就绪，后面所有初始化都有日志可看
          → Database / Cache / Storage / JWT / Hasher / CryptoBox
          → 注册中间件、异常处理器、路由
      → lifespan.startup
          → 探活 MySQL / Redis / MinIO（失败只警告，不阻断）
      → lifespan.shutdown
          → 释放连接池
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1 import health
from app.api.v1.auth import AuthController
from app.core.config import Settings, get_settings
from app.core.logging import LoggingConfigurator, log_startup_banner
from app.core.security import CryptoBox, JWTManager, PasswordHasher
from app.db.database import Database
from app.integrations.minio_storage import MinioStorage
from app.integrations.redis_client import build_cache
from app.middleware.exception import register_exception_handlers
from app.middleware.request_log import register_request_log
from app.services.bootstrap import AdminBootstrapper


class ApplicationFactory:
    """应用装配器。

    把所有「创建 → 注册 → 挂载」的步骤收在一个类里，
    避免 `main.py` 变成一长串散装语句。

    依赖实例都挂在 `app.state` 上，由 `app.core.deps` 取用 ——
    这是 FastAPI 推荐的共享方式，比模块级全局变量好测得多。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化工厂。

        Args:
            settings: 配置。不传则从环境变量加载（生产路径）。
        """
        self._settings = settings or get_settings()

    def create(self) -> FastAPI:
        """构建 FastAPI 应用。

        Returns:
            已完成装配的应用实例。
        """
        settings = self._settings

        # 日志必须最先初始化：后面任何一步失败，都要能看到原因
        LoggingConfigurator.setup(settings)
        log_startup_banner(settings)

        app = FastAPI(
            title=f"{settings.app.name} API",
            version="0.1.0",
            description="个人博客后端 · FastAPI + MySQL 8",
            # 生产环境关掉文档，避免把全部接口结构暴露给爬虫
            docs_url="/docs" if settings.is_debug else None,
            redoc_url=None,
            openapi_url="/openapi.json" if settings.is_debug else None,
            lifespan=self._lifespan,
        )

        # ---- 依赖实例 ----
        app.state.settings = settings
        app.state.db = Database(settings)
        app.state.cache = build_cache(settings)
        app.state.storage = MinioStorage(settings)
        app.state.jwt = JWTManager(
            secret=settings.jwt.secret.get_secret_value(),
            access_expire_minutes=settings.jwt.access_expire_minutes,
        )
        app.state.hasher = PasswordHasher()
        app.state.crypto = CryptoBox(settings.security.fernet_key.get_secret_value())

        if not app.state.crypto.is_secure:
            logger.warning("FERNET_KEY 未配置，模型 api_key 将以明文存储。生产环境必须配置。")

        # ---- 中间件 ----
        # CORS 必须最外层：否则异常响应（由内层中间件生成）不会带上 CORS 头，
        # 浏览器看到的是一句含糊的 "CORS error" 而不是真正的错误信息
        app.add_middleware(
            CORSMiddleware,
            # Go 版是 allow_origins=["*"]。开 credentials 时浏览器不允许通配符，
            # 本项目用 Bearer token 不走 Cookie，所以 close credentials 即可
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["Origin", "Content-Type", "Authorization"],
        )
        register_request_log(app)
        register_exception_handlers(app)

        # ---- 路由 ----
        # 注意：静态路径要注册在 {id} 之前（见 docs/README.md 的路由规范）
        app.include_router(health.router, prefix="/api/v1")
        app.include_router(AuthController().router, prefix="/api/v1")

        logger.info("应用装配完成，共 {} 条路由", len(app.routes))
        return app

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """启动 / 关闭钩子。

        Args:
            app: FastAPI 实例（由框架传入）。
        """
        settings: Settings = app.state.settings
        logger.info("开始初始化外部依赖…")

        # ---- 探活：失败只警告 ----
        # 依赖挂了不该让进程起不来：站点打不开 vs 图片上传失败，
        # 显然是后者损失更小。
        # 每个探活都单独包 try：任何一个 SDK 抛出意料之外的异常
        # （比如 minio 底层抛 urllib3 的 MaxRetryError），
        # 都不能把整个启动流程带崩。
        db_ok = await self._safe_probe("MySQL", self._check_database(app))
        cache_ok = await self._safe_probe("Redis", app.state.cache.ping())
        storage_ok = await self._safe_probe("MinIO", app.state.storage.ensure_bucket())

        logger.info(
            "依赖状态 | MySQL={} | Redis={} | MinIO={}",
            "OK" if db_ok else "FAIL",
            "OK" if cache_ok else "FAIL",
            "OK" if storage_ok else "FAIL",
        )

        # 管理员初始化放在探活之后：库都连不上时去插数据是徒劳。
        # 失败不阻断启动，见 AdminBootstrapper 的说明。
        if db_ok:
            await self._ensure_admin(app)

        if settings.is_debug:
            logger.info(
                "调试模式：接口文档 http://{}:{}/docs", settings.app.host, settings.app.port
            )

        logger.info("服务已就绪")
        try:
            yield
        finally:
            logger.info("正在关闭服务…")
            await app.state.db.dispose()
            await app.state.cache.close()
            logger.info("资源已释放")

    @staticmethod
    async def _safe_probe(name: str, probe: Any) -> bool:
        """执行一次探活，吞掉所有异常。

        Args:
            name: 依赖名，用于日志。
            probe: 可等待的探活协程。

        Returns:
            探活结果。异常时为 False。
        """
        try:
            return bool(await probe)
        except Exception as exc:  # noqa: BLE001 - 启动阶段不能让任何异常阻断
            logger.error("{} 探活异常：{}: {}", name, type(exc).__name__, exc)
            return False

    async def _ensure_admin(self, app: FastAPI) -> None:
        """确保库里有一个默认管理员。

        只在数据库探活成功时调用 —— 库都连不上还去插数据是徒劳。
        失败不抛异常，见 `AdminBootstrapper` 的说明。

        Args:
            app: 用于取 db / hasher / settings。
        """
        async with app.state.db.session() as session:
            bootstrapper = AdminBootstrapper(
                session=session,
                hasher=app.state.hasher,
                settings=app.state.settings,
            )
            await bootstrapper.ensure_admin()

    async def _check_database(self, app: FastAPI) -> bool:
        """数据库探活。

        Args:
            app: 用于取 `app.state.db`。

        Returns:
            是否连通。异常被吞掉并记日志，不向上抛。
        """
        from sqlalchemy import text

        try:
            async with app.state.db.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001 - 启动阶段要吞掉一切连接异常
            logger.error("MySQL 连接失败：{}", exc)
            return False


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用的工厂函数。

    uvicorn 的入口也走它，测试里可以传入自定义 `settings` 覆盖配置。

    Args:
        settings: 可选配置覆盖。

    Returns:
        FastAPI 实例。
    """
    return ApplicationFactory(settings).create()


# uvicorn app.main:app 的入口
app = create_app()
