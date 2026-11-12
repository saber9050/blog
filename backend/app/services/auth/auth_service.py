"""认证业务编排。

这一层是唯一放「业务规则」的地方：
格式校验、顺序判定、事务边界、Token 签发。
controller 只负责解析请求，repository 只负责 SQL。
"""

import secrets

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.security import JWTManager, PasswordHasher
from app.db.models import User
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import (
    EmailLoginRequest,
    ImageCaptchaResponse,
    IsExistsResponse,
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SendEmailCaptchaRequest,
    is_valid_account,
    is_valid_password,
)
from app.services.auth.auth_cache import AuthCache
from app.services.auth.captcha import ImageCaptchaGenerator
from app.services.auth.mailer import EmailSender


class AuthService:
    """认证核心。

    所有依赖构造注入，单测可以塞内存缓存、假邮件发送器，不用起 Redis / SMTP。
    """

    def __init__(
        self,
        session: AsyncSession,
        repo: AuthRepository,
        cache: AuthCache,
        captcha: ImageCaptchaGenerator,
        mailer: EmailSender,
        hasher: PasswordHasher,
        jwt_manager: JWTManager,
        settings: Settings,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话，用于控制事务提交。
            repo: 用户查询。
            cache: 验证码与会话缓存。
            captcha: 图形验证码生成器。
            mailer: 邮件发送器。
            hasher: 密码哈希。
            jwt_manager: JWT 签发解析。
            settings: 全局配置。
        """
        self._session = session
        self._repo = repo
        self._cache = cache
        self._captcha = captcha
        self._mailer = mailer
        self._hasher = hasher
        self._jwt = jwt_manager
        self._settings = settings

    # ============================================================
    # 注册
    # ============================================================

    async def register(self, req: RegisterRequest) -> None:
        """注册新用户。

        校验顺序**不能变**，否则错误提示会互相掩盖：
        比如密码格式错了却先提示「昵称已存在」，用户改了昵称还是注册不上。

        Raises:
            BizError: 账号格式(400) / 密码格式(400) / 两次不一致(400)
                / 昵称已存在(409) / 账号已存在(409)。
        """
        if not is_valid_account(req.account):
            raise BizError(ErrorCode.BAD_REQUEST, "账号格式错误")

        if not is_valid_password(req.password):
            raise BizError(ErrorCode.BAD_REQUEST, "密码格式错误")

        if req.password != req.ack:
            raise BizError(ErrorCode.BAD_REQUEST, "两次密码不一致")

        if await self._repo.exists_name(req.user_name):
            raise BizError(ErrorCode.CONFLICT, "该昵称已经存在")

        if await self._repo.exists_account(req.account):
            raise BizError(ErrorCode.CONFLICT, "该账号已经存在")

        user = User(
            user_name=req.user_name,
            account=req.account,
            password_hash=self._hasher.hash(req.password),
            status=1,
            role_id=0,
        )
        try:
            await self._repo.create(user)
            await self._session.commit()
        except Exception:
            # 唯一索引兜底：上面的 exists 检查与 insert 之间有窗口，
            # 并发注册同一个账号时只有数据库约束能拦住
            await self._session.rollback()
            raise

        logger.info("新用户注册成功 id={} account={}", user.id, req.account)

    # ============================================================
    # 登录
    # ============================================================

    async def login(self, req: LoginRequest) -> LoginResponse:
        """账号密码登录。

        Raises:
            BizError: 验证码过期/错误(400) / 账号不存在(404)
                / 被禁用(1004) / 密码错误(400)。
        """
        await self._verify_image_captcha(req.captcha_key, req.captcha_code)

        user = await self._repo.find_by_account(req.account)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "该账号不存在")

        self._ensure_active(user)

        if not self._hasher.verify(req.password, user.password_hash):
            raise BizError(ErrorCode.BAD_REQUEST, "密码错误")

        access_token = await self._issue_tokens(user)
        logger.info("用户登录成功 id={} account={}", user.id, req.account)
        return self._build_login_response(user, access_token)

    async def email_login(self, req: EmailLoginRequest) -> LoginResponse:
        """邮箱验证码登录。验证码通过后直接签发 Token，不验密码。

        Raises:
            BizError: 邮箱未注册(404) / 验证码错误(400) / 被禁用(1004)。
        """
        user = await self._repo.find_by_email(req.email)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "该邮箱未注册")

        self._ensure_active(user)
        await self.verify_email_captcha(req.email, req.purpose, req.captcha)

        access_token = await self._issue_tokens(user)
        logger.info("邮箱验证码登录成功 id={} email={}", user.id, req.email)
        return self._build_login_response(user, access_token)

    # ============================================================
    # 验证码
    # ============================================================

    async def send_image_captcha(self) -> ImageCaptchaResponse:
        """生成图形验证码并写入缓存。

        Returns:
            captcha_id（即缓存 key）与可直接塞 `<img>` 的 data URI。
        """
        answer, data_uri = await self._captcha.generate()
        # 用随机 key 而不是把答案编码进 id：id 泄露不等于答案泄露
        captcha_id = secrets.token_urlsafe(16)
        await self._cache.store_image_captcha(captcha_id, answer)
        return ImageCaptchaResponse(captcha_id=captcha_id, base_64=data_uri)

    async def send_email_captcha(self, req: SendEmailCaptchaRequest) -> None:
        """发送邮箱验证码。

        执行顺序（与方案文档略有调整，原因见下）：

            1. SETNX 占发信配额
            2. 写验证码缓存
            3. 发邮件
            4. 发信失败 → 回滚配额 + 删缓存

        方案原文是「先写缓存，再判频率」，但那样有个副作用：
        用户在冷却期内再次点发送，新的验证码会覆盖缓存里旧的那个，
        而他手上收到的是旧邮件 —— 新码进了缓存、旧码失效，登录必然失败。
        先占配额就不会误伤已发出的验证码。

        Raises:
            BizError: 频繁(400) / 发送失败(500)。
        """
        if not await self._cache.acquire_send_limit(req.email):
            raise BizError(ErrorCode.BAD_REQUEST, "请勿频繁发送验证码，请60秒后再试")

        code = self._generate_numeric_code()
        await self._cache.store_email_captcha(req.email, code, req.purpose)

        try:
            await self._mailer.send_captcha(req.email, code, req.purpose)
        except BizError:
            # 发信失败要把两样都撤掉，否则用户既收不到信、又得等 60 秒
            await self._cache.release_send_limit(req.email)
            await self._cache.delete_email_captcha(req.email, req.purpose)
            raise

    async def reset_password(self, req: ResetPasswordRequest) -> None:
        """邮箱验证码重置密码。

        改密后**不踢已登录设备**：旧 access token 15 分钟内自然过期。
        要强制下线就删 `refresh:{user_id}`，本轮不做（见 openspec 第 10 节）。

        Raises:
            BizError: 两次不一致(400) / 密码格式(400) / 邮箱未注册(404)
                / 验证码错误(400)。
        """
        if req.new_password != req.ack:
            raise BizError(ErrorCode.BAD_REQUEST, "两次密码不一致")

        if not is_valid_password(req.new_password):
            raise BizError(ErrorCode.BAD_REQUEST, "密码格式错误")

        user = await self._repo.find_by_email(req.email)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "该邮箱未注册")

        # purpose 固定 reset_password：不同用途的验证码不能混用，
        # 否则「登录验证码」能拿来改密码
        await self.verify_email_captcha(req.email, "reset_password", req.captcha)

        await self._repo.update_password(user.id, self._hasher.hash(req.new_password))
        await self._session.commit()
        logger.info("用户重置密码成功 id={}", user.id)

    # ============================================================
    # 会话
    # ============================================================

    async def refresh(self, access_token: str) -> RefreshTokenResponse:
        """用（可能已过期的）access token 换新的 access token。

        **必须用 `verify_exp=False` 解析**：access token 一过期就换不了新 token，
        那双 Token 机制就白设计了。

        Raises:
            BizError: 401 refresh 不存在 / tid 不匹配 / 用户失效。
        """
        try:
            claims = self._jwt.decode(access_token, verify_exp=False)
        except BizError as exc:
            # 1005「无效的令牌」映射到 HTTP 400，但刷新接口文档要求 401，
            # 且文案是「Access Token 无效」。这里统一转成 401。
            if exc.code == ErrorCode.INVALID_TOKEN:
                raise BizError(ErrorCode.UNAUTHORIZED, "Access Token 无效") from exc
            raise

        stored = await self._cache.get_refresh_token(claims.user_id)
        if not stored:
            raise BizError(ErrorCode.UNAUTHORIZED, "Refresh Token 已过期，请重新登录")

        if stored != claims.tid:
            # 典型场景：同一账号在别处登录，当前设备的会话已被顶掉
            raise BizError(ErrorCode.UNAUTHORIZED, "Refresh Token 无效，请重新登录")

        user = await self._repo.find_by_id(claims.user_id)
        if user is None:
            await self._cache.delete_refresh_token(claims.user_id)
            raise BizError(ErrorCode.UNAUTHORIZED, "用户不存在，请重新登录")
        self._ensure_active(user)

        # 轮换：新 refresh 覆盖旧的，旧 access 的 tid 立即失效
        access_token = await self._issue_tokens(user)
        return RefreshTokenResponse(access_token=access_token)

    async def logout(self, access_token: str) -> None:
        """登出。

        **幂等**：token 缺失、格式错、已过期一律当成功返回。
        前端登出按钮不该因为 token 过期而弹错误框。

        只有当前会话的 tid 与缓存一致时才删 key，
        否则会出现「手机登出把电脑端踢下线」。
        """
        try:
            claims = self._jwt.decode(access_token, verify_exp=False)
        except BizError:
            return None

        stored = await self._cache.get_refresh_token(claims.user_id)
        if stored and stored == claims.tid:
            await self._cache.delete_refresh_token(claims.user_id)
            logger.info("用户登出 id={}", claims.user_id)
        return None

    # ============================================================
    # 唯一性检测
    # ============================================================

    async def is_exists_name(self, user_name: str) -> IsExistsResponse:
        """昵称是否已被占用。"""
        return IsExistsResponse(is_exists=await self._repo.exists_name(user_name))

    async def is_exists_account(self, account: str) -> IsExistsResponse:
        """账号是否已被占用。"""
        return IsExistsResponse(is_exists=await self._repo.exists_account(account))

    # ============================================================
    # 内部方法
    # ============================================================

    async def _issue_tokens(self, user: User) -> str:
        """签发会话并返回 access token。

        refresh token 只写进缓存和 access 的 `tid`，**不返回给前端**：
        前端拿不到长期凭证，XSS 也偷不走。

        Args:
            user: 已通过身份校验的用户。

        Returns:
            access token 字符串。
        """
        refresh_token = JWTManager.generate_refresh_token()
        access_token = self._jwt.create_access_token(
            user_id=user.id,
            username=user.user_name,
            role_id=user.role_id,
            tid=refresh_token,
        )
        await self._cache.store_refresh_token(
            user.id,
            refresh_token,
            ttl_seconds=self._settings.jwt.refresh_expire_hours * 3600,
        )
        return access_token

    def _build_login_response(self, user: User, access_token: str) -> LoginResponse:
        """组装登录响应。字段名与 Go 版一致（user_role_id 不是 role_id）。"""
        return LoginResponse(
            user_name=user.user_name,
            user_id=user.id,
            user_role_id=user.role_id,
            access_token=access_token,
        )

    def _ensure_active(self, user: User) -> None:
        """校验账号未被禁用。

        Raises:
            BizError: 1004 用户已被禁用。
        """
        if user.status == 0:
            raise BizError(ErrorCode.USER_DISABLED, "用户已被禁用")

    async def _verify_image_captcha(self, captcha_key: str, code: str) -> None:
        """校验图形验证码。

        **无论对错都删 key**：
        - 成功删：防止同一个验证码被重复使用
        - 失败删：防止在 300 秒内反复爆破同一个 key

        Raises:
            BizError: 400 已过期 / 400 错误。
        """
        expected = await self._cache.get_image_captcha(captcha_key)
        if expected is None:
            raise BizError(ErrorCode.BAD_REQUEST, "验证码已过期")

        # 先删再比：即使比对抛异常，key 也已经没了
        await self._cache.delete_image_captcha(captcha_key)

        if expected.strip().lower() != code.strip().lower():
            raise BizError(ErrorCode.BAD_REQUEST, "验证码错误")

    async def verify_email_captcha(self, email: str, purpose: str, code: str) -> None:
        """校验邮箱验证码。

        与图形验证码不同：**只在成功后删除**。
        邮箱验证码本来就只发到本人邮箱，不存在被爆破的前提，
        而输错一次就得重新等一分钟邮件，体验太差。

        Raises:
            BizError: 400 已过期 / 400 错误。
        """
        expected = await self._cache.get_email_captcha(email, purpose)
        if expected is None:
            raise BizError(ErrorCode.BAD_REQUEST, "验证码已过期")

        if expected != code.strip():
            raise BizError(ErrorCode.BAD_REQUEST, "验证码错误")

        await self._cache.delete_email_captcha(email, purpose)

    def _generate_numeric_code(self) -> str:
        """生成 6 位数字验证码。

        用 `secrets` 而不是 `random`：`random` 是可预测的伪随机，
        邮箱验证码被猜到等于账号被接管。

        Returns:
            6 位数字字符串（允许前导零）。
        """
        length = self._settings.business.captcha_length
        return "".join(secrets.choice("0123456789") for _ in range(length))
