"""用户资料与账号设置。

`UserService` 依赖 `AuthService` 的两个能力：校验邮箱验证码、签发一次性 token。
**不复制实现**：验证码用途写错、密码规则改了这类问题，改两处必然漏一处。
"""

import secrets
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.protocols import SupportsFileStorage
from app.core.security import JWTManager, PasswordHasher
from app.core.timefmt import format_time_z
from app.db.models import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import is_valid_account, is_valid_password
from app.schemas.user import (
    AddEmailRequest,
    AdminCreateUserRequest,
    AdminUserItem,
    AdminUserListResponse,
    AdminUserQuery,
    UpdateEmailRequest,
    UpdatePasswordRequest,
    UpdateProfileRequest,
    UserInfoResponse,
)
from app.services.auth.auth_cache import AuthCache
from app.services.auth.auth_service import AuthService
from app.services.auth.mailer import EmailSender

# 扩展名 → MIME。只允许这 4 种，与文档一致
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# 换绑邮箱确认链接的有效期
_EMAIL_CONFIRM_TOKEN_SECONDS = 300


class UserService:
    """用户资料、头像、密码、邮箱，以及后台用户管理。"""

    def __init__(
        self,
        session: AsyncSession,
        repo: UserRepository,
        auth_service: AuthService,
        cache: AuthCache,
        storage: SupportsFileStorage,
        mailer: EmailSender,
        hasher: PasswordHasher,
        jwt_manager: JWTManager,
        settings: Settings,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话（控制事务）。
            repo: 用户读写。
            auth_service: 复用验证码校验能力。
            cache: 一次性 token 黑名单。
            storage: 对象存储。
            mailer: 邮件发送。
            hasher: 密码哈希。
            jwt_manager: 签发确认链接的 token。
            settings: 全局配置。
        """
        self._session = session
        self._repo = repo
        self._auth = auth_service
        self._cache = cache
        self._storage = storage
        self._mailer = mailer
        self._hasher = hasher
        self._jwt = jwt_manager
        self._settings = settings

    # ============================================================
    # 前台：资料
    # ============================================================

    async def get_info(self, user_id: int) -> UserInfoResponse:
        """取当前用户资料。

        `avatar_url` 库里存的是 object key，这里拼成完整 URL；
        `email` / `introduction` / `avatar_url` 为空时统一返回 `""`
        而不是 `null`，前端不用做 null 判断。

        Raises:
            BizError: 404 用户不存在。
        """
        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        return UserInfoResponse(
            user_id=user.id,
            user_name=user.user_name,
            account=user.account,
            email=user.email or "",
            avatar_url=self._storage.public_url(user.avatar_url or ""),
            introduction=user.introduction or "",
            role_id=user.role_id,
            staus=user.status,
            create_at=format_time_z(user.created_at),
        )

    async def update_profile(self, user_id: int, req: UpdateProfileRequest) -> None:
        """更新昵称与简介。

        三态语义：
        - `None`（不传 / 传 null）→ 不修改
        - `""` → 昵称**不修改**（昵称是 NOT NULL + 唯一，不能清空）；
          简介**清空**
        - 有内容 → 改成新值

        昵称查重会排除自己，所以「昵称原样提交、只改简介」不会误报已存在。

        Raises:
            BizError: 409 昵称被他人占用。
        """
        fields: dict[str, object] = {}

        if req.nick_name is not None and req.nick_name.strip():
            new_name = req.nick_name.strip()
            if await self._repo.exists_name_excluding(new_name, exclude_id=user_id):
                raise BizError(ErrorCode.CONFLICT, "该昵称已经存在")
            fields["user_name"] = new_name

        if req.introduction is not None:
            # 传 "" 就是要清空。Go 版用 `!= ""` 判断，导致简介永远清不掉
            fields["introduction"] = req.introduction

        if not fields:
            return

        await self._repo.update_fields(user_id, **fields)
        await self._session.commit()
        logger.info("用户资料已更新 id={} fields={}", user_id, list(fields))

    async def update_avatar(self, user_id: int, file: UploadFile) -> str:
        """上传头像。

        流程：校验大小/格式 → 传 MinIO → 更新库 → 删旧图。
        删旧图失败只记日志：图已经换好了，不能因为清理失败让用户以为没成功。

        Args:
            user_id: 当前用户。
            file: 上传的文件。

        Returns:
            新头像的完整 URL。

        Raises:
            BizError: 400 超限或格式不支持 / 500 上传失败。
        """
        ext = Path(file.filename or "").suffix.lower()
        if ext not in self._settings.business.allowed_image_exts:
            raise BizError(ErrorCode.BAD_REQUEST, "不支持的文件格式")

        data = await file.read()
        max_bytes = self._settings.business.image_max_bytes
        if len(data) > max_bytes:
            raise BizError(ErrorCode.BAD_REQUEST, "图片大小不能超过 10MB")
        if not data:
            raise BizError(ErrorCode.BAD_REQUEST, "不支持的文件格式")

        # 按日期分目录：单目录文件数过万后，对象存储的 list 操作会明显变慢
        today = datetime.now().strftime("%Y%m%d")
        object_name = f"all/{today}/{secrets.token_hex(8)}{ext}"

        await self._storage.upload(object_name, data, _EXT_TO_MIME[ext])

        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")
        old_key = user.avatar_url or ""

        await self._repo.update_fields(user_id, avatar_url=object_name)
        await self._session.commit()

        if old_key and old_key != object_name:
            # 失败只 warn：不能因为删不掉旧图就报错回滚
            await self._storage.delete(old_key)

        logger.info("头像已更新 id={} key={}", user_id, object_name)
        return self._storage.public_url(object_name)

    async def update_password(self, user_id: int, req: UpdatePasswordRequest) -> None:
        """凭旧密码改新密码。

        改完**不踢下线**：旧 access token 15 分钟内自然过期（Go 版行为）。

        Raises:
            BizError: 400 旧密码错 / 两次不一致 / 新密码格式错。
        """
        if req.new_password != req.ack:
            raise BizError(ErrorCode.BAD_REQUEST, "两次密码不一致")
        if not is_valid_password(req.new_password):
            raise BizError(ErrorCode.BAD_REQUEST, "密码格式错误")

        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        if not self._hasher.verify(req.old_password, user.password_hash):
            raise BizError(ErrorCode.BAD_REQUEST, "密码错误")

        await self._repo.update_fields(user_id, password_hash=self._hasher.hash(req.new_password))
        await self._session.commit()
        logger.info("用户修改密码 id={}", user_id)

    # ============================================================
    # 前台：邮箱
    # ============================================================

    async def request_email_change(self, user_id: int, req: UpdateEmailRequest) -> None:
        """申请换绑邮箱（第一段）。

        **不改库**：验证「当前密码 + 发到当前邮箱的验证码」证明操作者是本人，
        然后给**新邮箱**发一封带 token 的链接。用户点开才真正写库 ——
        这样能证明「新邮箱确实属于本人」。

        Raises:
            BizError: 400 验证码/密码错 / 409 新邮箱被占用 / 429 频繁 / 500 发信失败。
        """
        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        # 1. 验证码（发到当前邮箱）。账号没有邮箱时这一步必然失败，
        #    那种场景应该走 /user/add_email
        if not user.email:
            raise BizError(ErrorCode.BAD_REQUEST, "当前账号未绑定邮箱，请先绑定")
        await self._auth.verify_email_captcha(user.email, "reset_email", req.captcha)

        # 2. 密码
        if not self._hasher.verify(req.password, user.password_hash):
            raise BizError(ErrorCode.BAD_REQUEST, "密码错误")

        # 3. 新邮箱不能被别人占用（自己当前邮箱除外）
        if req.new_email != user.email and await self._repo.exists_email(req.new_email):
            raise BizError(ErrorCode.CONFLICT, "该邮箱已经被绑定")

        # 4. 频率限制：用新邮箱做 key，防止连点刷邮件
        if not await self._cache.acquire_send_limit(req.new_email):
            raise BizError(ErrorCode.TOO_MANY_REQUESTS, "请勿频繁发送验证码，请60秒后再试")

        # 5. 签发一次性 token 并发邮件
        #    注意 `username` 字段里放的是**新邮箱**，照抄 Go 的历史包袱
        token = self._jwt.create_purpose_token(
            {"user_id": user_id, "username": req.new_email},
            expire_seconds=_EMAIL_CONFIRM_TOKEN_SECONDS,
        )
        link = f"{self._settings.app.site_url.rstrip('/')}/api/v1/user/email?token={token}"

        try:
            await self._mailer.send_email_change_link(
                req.new_email, link, _EMAIL_CONFIRM_TOKEN_SECONDS // 60
            )
        except BizError:
            # 发信失败要回滚配额，否则用户白等 60 秒
            await self._cache.release_send_limit(req.new_email)
            raise

        logger.info("换绑邮箱确认邮件已发出 id={} new_email={}", user_id, req.new_email)

    async def confirm_email(self, token: str) -> None:
        """确认换绑（第二段）。token 用一次即作废。

        服务层只管「改没改成功」；渲染成什么样是 Controller 的事 ——
        换样式不该动业务逻辑。

        Raises:
            BizError: 401 token 无效/过期 / 403 已使用过。
        """
        if await self._cache.is_token_blacklisted(token):
            raise BizError(ErrorCode.FORBIDDEN, "该token已无效")

        payload = self._jwt.decode_raw(token)
        user_id = payload.get("user_id")
        # 历史包袱：字段名叫 username，存的其实是新邮箱
        new_email = payload.get("username")

        if not user_id or not new_email:
            raise BizError(ErrorCode.INVALID_TOKEN, "无效的令牌")

        user = await self._repo.find_by_id(int(user_id))
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        await self._repo.update_fields(int(user_id), email=str(new_email))
        await self._session.commit()

        # 拉黑：链接在有效期内可以被重复点击，不拉黑会重复写库
        await self._cache.blacklist_token(token, ttl_seconds=_EMAIL_CONFIRM_TOKEN_SECONDS)
        logger.info("邮箱换绑成功 id={} new_email={}", user_id, new_email)

    async def add_email(self, user_id: int, req: AddEmailRequest) -> None:
        """首次补绑邮箱。直接生效，不发确认邮件。

        Raises:
            BizError: 403 已有邮箱 / 400 验证码错 / 409 邮箱被占用。
        """
        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        if user.email:
            # 403 而不是 400：这是 Go 版的行为，前端按状态码分支时依赖它
            raise BizError(ErrorCode.FORBIDDEN, "用户已存在邮箱，不可再添加")

        await self._auth.verify_email_captcha(req.new_email, "add_email", req.captcha)

        if await self._repo.exists_email(req.new_email):
            raise BizError(ErrorCode.CONFLICT, "该邮箱已经被绑定")

        await self._repo.update_fields(user_id, email=req.new_email)
        await self._session.commit()
        logger.info("用户补绑邮箱 id={} email={}", user_id, req.new_email)

    async def is_exists_email(self, email: str) -> bool:
        """邮箱是否已被占用。"""
        return await self._repo.exists_email(email)

    # ============================================================
    # 后台
    # ============================================================

    async def admin_list(self, query: AdminUserQuery) -> AdminUserListResponse:
        """后台用户列表。

        只返回 `role_id=0` 的普通用户；管理员不混进来，
        避免「禁用用户」时误操作把自己禁掉。
        """
        rows, total = await self._repo.paginate(
            page=query.page,
            page_size=query.page_size,
            keyword=query.keyword,
            status=query.status,
            start_time=query.start_time,
            end_time=query.end_time,
        )
        items = [
            AdminUserItem(
                id=u.id,
                user_name=u.user_name,
                avatar_url=self._storage.public_url(u.avatar_url or ""),
                status=u.status,
                created_at=format_time_z(u.created_at),
            )
            for u in rows
        ]
        return AdminUserListResponse(
            list=items,
            total=total,
            page=query.page,
            pageSize=query.page_size,  # 驼峰是契约
        )

    async def admin_create(self, req: AdminCreateUserRequest) -> int:
        """后台创建用户，返回新 ID。

        Raises:
            BizError: 400 账号/密码格式 / 409 昵称或账号已存在。
        """
        if not is_valid_account(req.account):
            raise BizError(ErrorCode.BAD_REQUEST, "账号格式错误")
        if not is_valid_password(req.password):
            raise BizError(ErrorCode.BAD_REQUEST, "密码格式错误")

        if await self._repo.exists_name_excluding(req.user_name, exclude_id=0):
            raise BizError(ErrorCode.CONFLICT, "该昵称已经存在")
        if await self._repo.exists_account(req.account):
            raise BizError(ErrorCode.CONFLICT, "该账号已经存在")

        user = User(
            user_name=req.user_name,
            account=req.account,
            password_hash=self._hasher.hash(req.password),
            status=req.status,
            role_id=0,
        )
        self._session.add(user)
        await self._session.flush()
        await self._session.commit()
        logger.info("后台创建用户 id={} account={}", user.id, req.account)
        return user.id

    async def admin_update_status(self, user_id: int, status: int, operator_id: int) -> None:
        """启用 / 禁用。

        Raises:
            BizError: 400 改自己 / 404 用户不存在。
        """
        if user_id == operator_id:
            raise BizError(ErrorCode.BAD_REQUEST, "不能修改自己的状态")

        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        await self._repo.update_fields(user_id, status=status)
        await self._session.commit()
        logger.info("用户状态已更新 id={} status={}", user_id, status)

    async def admin_delete(self, user_id: int, operator_id: int) -> None:
        """软删除用户。不级联删文章与评论，作者名会显示为空。

        Raises:
            BizError: 400 删自己 / 404 用户不存在。
        """
        if user_id == operator_id:
            raise BizError(ErrorCode.BAD_REQUEST, "不能删除自己")

        user = await self._repo.find_by_id(user_id)
        if user is None:
            raise BizError(ErrorCode.NOT_FOUND, "用户不存在")

        await self._repo.soft_delete(user_id)
        await self._session.commit()
        logger.info("用户已软删除 id={}", user_id)
