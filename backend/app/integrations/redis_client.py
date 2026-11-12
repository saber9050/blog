"""Redis 客户端封装。

不直接暴露 `redis.asyncio.Redis`，而是包一层，原因：

1. 业务代码只需要 `SupportsCache` 那几个方法，暴露原生客户端会让
   「顺手写个 pipeline」这种用法扩散出去，单测就没法替换了。
2. 未配置 Redis 时可以降级到进程内字典（`InMemoryCache`），
   本地开发不用先起 Redis 就能跑通登录流程。

⚠️ 内存降级只在单 worker 下有意义：多进程之间不共享，
图形验证码会「这台机器发的、那台机器验不过」。
生产必须开 Redis，启动日志会提示。
"""

import time
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings


class RedisClient:
    """Redis 实现。

    所有方法吞掉连接异常并降级为「缓存不可用」而不是抛 500 ——
    验证码取不到会让用户重试，但整站不该因为 Redis 挂了就打不开。
    唯一例外是 `set_if_absent`：它被用来做发信频率限制，
    失败时返回 False（当作「已限流」）比放行更安全。
    """

    def __init__(self, settings: Settings) -> None:
        """创建连接池。

        Args:
            settings: 从里面取 host / port / password / db。
        """
        password = settings.database.redis.password.get_secret_value() or None
        self._client: Redis = Redis(
            host=settings.database.redis.host,
            port=settings.database.redis.port,
            password=password,
            db=settings.database.redis.db,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )

    async def ping(self) -> bool:
        """探活。启动时调用，失败只打警告不阻断启动。"""
        try:
            return bool(await self._client.ping())
        except (RedisError, OSError) as exc:
            logger.warning("Redis 连接失败，缓存相关功能将不可用：{}", exc)
            return False

    async def close(self) -> None:
        """关闭连接池。shutdown 时调用。"""
        await self._client.aclose()

    # ---------- SupportsCache 实现 ----------

    async def get(self, key: str) -> str | None:
        """读字符串。Redis 不可用时返回 None（调用方当作「不存在」）。"""
        try:
            return await self._client.get(key)
        except (RedisError, OSError) as exc:
            logger.warning("Redis GET 失败 key={}：{}", key, exc)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        """写字符串。ttl 为 None 表示不过期。"""
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except (RedisError, OSError) as exc:
            logger.warning("Redis SET 失败 key={}：{}", key, exc)

    async def delete(self, key: str) -> None:
        """删除键。"""
        try:
            await self._client.delete(key)
        except (RedisError, OSError) as exc:
            logger.warning("Redis DEL 失败 key={}：{}", key, exc)

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        """键不存在时写入（SET NX EX）。

        Returns:
            True 写入成功 / False 键已存在。
            Redis 异常时返回 False —— 频率限制宁可误拦，不能放行。
        """
        try:
            result = await self._client.set(key, value, ex=ttl_seconds, nx=True)
            return bool(result)
        except (RedisError, OSError) as exc:
            logger.warning("Redis SETNX 失败 key={}：{}", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        """键是否存在。用于「token 是否已被拉黑」这类判断。"""
        try:
            return bool(await self._client.exists(key))
        except (RedisError, OSError) as exc:
            logger.warning("Redis EXISTS 失败 key={}：{}", key, exc)
            return False

    async def ttl(self, key: str) -> int:
        """剩余生存秒数。-1 表示永不过期，-2 表示键不存在。"""
        try:
            return int(await self._client.ttl(key))
        except (RedisError, OSError) as exc:
            logger.warning("Redis TTL 失败 key={}：{}", key, exc)
            return -2


class InMemoryCache:
    """进程内缓存，仅在 `REDIS_ENABLED=false` 时使用。

    故意做成最简实现（一个 dict + 过期时间戳），不追求淘汰策略：
    它的唯一用途是本地开发时能跑通登录流程，不需要承载真实流量。
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _is_expired(self, key: str) -> bool:
        """判断键是否过期，顺带清理。"""
        item = self._store.get(key)
        if item is None:
            return True
        _, expire_at = item
        if expire_at is not None and expire_at <= time.monotonic():
            self._store.pop(key, None)
            return True
        return False

    async def get(self, key: str) -> str | None:
        if self._is_expired(key):
            return None
        return self._store[key][0]

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expire_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        self._store[key] = (value, expire_at)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        if not self._is_expired(key):
            return False
        await self.set(key, value, ttl_seconds)
        return True

    async def exists(self, key: str) -> bool:
        return not self._is_expired(key)

    async def ttl(self, key: str) -> int:
        if self._is_expired(key):
            return -2
        _, expire_at = self._store[key]
        if expire_at is None:
            return -1
        return int(expire_at - time.monotonic())

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._store.clear()


def build_cache(settings: Settings) -> Any:
    """按配置选缓存实现。

    Args:
        settings: `redis_enabled` 决定用真实 Redis 还是内存降级。

    Returns:
        RedisClient 或 InMemoryCache，两者都满足 `SupportsCache` 契约。
    """
    if settings.database.redis.enabled:
        return RedisClient(settings)
    logger.warning(
        "REDIS_ENABLED=false，已降级为进程内缓存。多 worker 部署时验证码会失效，仅限本地开发使用。"
    )
    return InMemoryCache()


__all__ = ["InMemoryCache", "RedisClient", "build_cache"]
