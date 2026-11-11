"""认证相关缓存。

所有 Redis key 在这里统一拼装，业务代码禁止手写字符串 ——
改一次前缀要全库搜是很蠢的事。
"""

from app.core.protocols import SupportsCache


class AuthCache:
    """认证缓存的读写门面。

    只依赖 `SupportsCache` 契约，不关心背后是 Redis 还是内存降级实现。
    """

    # ---- key 模板 ----
    # 改动会直接影响存量会话（已登录用户的 refresh 失效），非必要不动
    CAPTCHA_IMAGE = "captcha:login:{key}"
    CAPTCHA_EMAIL = "captcha:email:{email}:{purpose}"
    EMAIL_LIMIT = "captcha:limit:{email}"
    REFRESH_TOKEN = "refresh:{user_id}"
    # 一次性 token 黑名单（目前用于换绑邮箱的确认链接）
    TOKEN_BLACKLIST = "blacklist:token:{token}"

    def __init__(
        self,
        cache: SupportsCache,
        captcha_ttl: int = 300,
        send_limit_ttl: int = 60,
    ) -> None:
        """初始化。

        Args:
            cache: 缓存实现（Redis 或内存降级）。
            captcha_ttl: 验证码有效期（秒）。
            send_limit_ttl: 同一邮箱发信冷却时间（秒）。
        """
        self._cache = cache
        self._captcha_ttl = captcha_ttl
        self._send_limit_ttl = send_limit_ttl

    # ---------- 图形验证码 ----------

    async def store_image_captcha(self, key: str, answer: str) -> None:
        """存图形验证码答案。

        TTL 固定 300 秒。每次请求都生成新的 key，旧的不主动删（到期自动清）。
        """
        await self._cache.set(
            self.CAPTCHA_IMAGE.format(key=key), answer, ttl_seconds=self._captcha_ttl
        )

    async def get_image_captcha(self, key: str) -> str | None:
        """取图形验证码答案。不存在（或已过期）返回 None。"""
        return await self._cache.get(self.CAPTCHA_IMAGE.format(key=key))

    async def delete_image_captcha(self, key: str) -> None:
        """删图形验证码。

        登录时**无论校验成功还是失败都要删**：
        成功删是防止同一个验证码被重复使用；失败删是防止暴力猜。
        """
        await self._cache.delete(self.CAPTCHA_IMAGE.format(key=key))

    # ---------- 邮箱验证码 ----------

    async def store_email_captcha(self, email: str, code: str, purpose: str) -> None:
        """存邮箱验证码。不同 purpose 用不同 key，互不覆盖。"""
        await self._cache.set(
            self.CAPTCHA_EMAIL.format(email=email, purpose=purpose),
            code,
            ttl_seconds=self._captcha_ttl,
        )

    async def get_email_captcha(self, email: str, purpose: str) -> str | None:
        """取邮箱验证码。"""
        return await self._cache.get(self.CAPTCHA_EMAIL.format(email=email, purpose=purpose))

    async def delete_email_captcha(self, email: str, purpose: str) -> None:
        """删邮箱验证码。校验通过后删除，防止同码二次使用。"""
        await self._cache.delete(self.CAPTCHA_EMAIL.format(email=email, purpose=purpose))

    # ---------- 发信频率限制 ----------

    async def acquire_send_limit(self, email: str) -> bool:
        """占位发信配额。

        用 SET NX EX 原子操作，避免「先 GET 再 SET」中间被并发插队。

        Args:
            email: 接收邮箱。**只按邮箱限制，不分 purpose** ——
                否则用户可以轮流用 4 个 purpose 绕过 60 秒冷却。

        Returns:
            True 拿到配额（可以发），False 冷却中。
        """
        return await self._cache.set_if_absent(
            self.EMAIL_LIMIT.format(email=email), "1", ttl_seconds=self._send_limit_ttl
        )

    async def release_send_limit(self, email: str) -> None:
        """回滚发信配额。

        发信失败时调用，否则用户要白等 60 秒才能重试 ——
        SMTP 抽风的那一分钟里，用户完全无法操作。
        """
        await self._cache.delete(self.EMAIL_LIMIT.format(email=email))

    # ---------- refresh token ----------

    async def store_refresh_token(self, user_id: int, token: str, ttl_seconds: int) -> None:
        """存当前会话的 refresh token。

        **覆盖写**：同一用户只保留一个有效会话，这就是「单设备登录」的实现方式。
        新设备登录会顶掉旧设备的会话。
        """
        await self._cache.set(
            self.REFRESH_TOKEN.format(user_id=user_id), token, ttl_seconds=ttl_seconds
        )

    async def get_refresh_token(self, user_id: int) -> str | None:
        """取当前会话的 refresh token。"""
        return await self._cache.get(self.REFRESH_TOKEN.format(user_id=user_id))

    async def delete_refresh_token(self, user_id: int) -> None:
        """删 refresh token（登出）。"""
        await self._cache.delete(self.REFRESH_TOKEN.format(user_id=user_id))

    # ---------- 一次性 token 黑名单 ----------

    async def blacklist_token(self, token: str, ttl_seconds: int = 300) -> None:
        """把用过的 token 拉黑。

        用于「换绑邮箱确认链接」这类一次性凭证：
        链接在有效期内可以被重复点击，不拉黑就会重复写库。
        TTL 与 token 自身有效期一致即可 —— 过期后再拉黑没意义。

        Args:
            token: 原始 JWT 字符串。
            ttl_seconds: 保留多久。
        """
        await self._cache.set(
            self.TOKEN_BLACKLIST.format(token=token), "1", ttl_seconds=ttl_seconds
        )

    async def is_token_blacklisted(self, token: str) -> bool:
        """token 是否已被使用过。"""
        return await self._cache.get(self.TOKEN_BLACKLIST.format(token=token)) is not None
