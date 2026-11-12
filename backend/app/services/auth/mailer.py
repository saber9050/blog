"""SMTP 邮件发送。

QQ 邮箱用 587 端口 + STARTTLS。smtplib 是同步阻塞的，
必须丢到线程池，否则一封慢邮件能卡住整个事件循环 ——
一个用户点「发送验证码」，所有人的请求都排队等它。
"""

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from anyio import to_thread
from loguru import logger

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode

# 按用途渲染标题与导语。
# 不做成 HTML 模板：验证码邮件越简单越不容易被判定为垃圾邮件，
# 而且纯文本在手机上反而清晰。
_PURPOSE_TEXT: dict[str, tuple[str, str]] = {
    "login": ("登录验证码", "你正在使用邮箱验证码登录，验证码为："),
    "reset_password": ("重置密码验证码", "你正在重置密码，验证码为："),
    "reset_email": ("修改邮箱验证码", "你正在修改绑定邮箱，验证码为："),
    "add_email": ("绑定邮箱验证码", "你正在绑定邮箱，验证码为："),
}


class EmailSender:
    """验证码邮件发送器。

    两种模式：
    - 配了 `smtp.username`：真实发送
    - 没配且处于 debug 模式：**只把验证码打进日志**，不发信。
      本地开发不可能为了测登录去配 SMTP 授权码，这个降级让「邮箱验证码登录」
      在本地也能走通完整流程。
    - 没配且是 release 模式：直接报 500，绝不静默吞掉
    """

    def __init__(self, settings: Settings) -> None:
        """初始化。

        Args:
            settings: 取 `smtp` 分组与 `app.mode`。
        """
        self._settings = settings
        self._smtp = settings.smtp

    @property
    def is_configured(self) -> bool:
        """是否配置了可用的 SMTP 账号。"""
        return bool(self._smtp.username and self._smtp.password.get_secret_value())

    async def send_captcha(self, to_email: str, code: str, purpose: str) -> None:
        """发送验证码邮件。

        Args:
            to_email: 收件地址。
            code: 6 位验证码。
            purpose: 用途，决定标题与导语。

        Raises:
            BizError: 500 发送失败（连接超时、认证失败、收件人被拒）。
        """
        subject, intro = _PURPOSE_TEXT.get(purpose, ("验证码", "你的验证码为："))

        if not self.is_configured:
            self._handle_unconfigured(to_email, code, purpose)
            return

        message = self._build_message(to_email, subject, intro, code)

        try:
            # smtplib 是同步的，必须离开事件循环
            await to_thread.run_sync(self._send_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            # 对外统一文案，不把 SMTP 的内部错误（可能含服务器地址、账号）抛给前端
            logger.error("发送验证码邮件失败 to={} purpose={}：{}", to_email, purpose, exc)
            raise BizError(ErrorCode.INTERNAL_ERROR, "发送邮箱验证码失败") from exc

        logger.info("验证码邮件已发送 to={} purpose={}", to_email, purpose)

    def _handle_unconfigured(self, to_email: str, code: str, purpose: str) -> None:
        """SMTP 未配置时的处理。

        debug 模式把验证码打到日志，让本地能测；
        release 模式必须报错 —— 生产环境静默吞掉验证码，用户会一直等一封永远不会来的邮件。

        Raises:
            BizError: release 模式下 500。
        """
        if self._settings.is_debug:
            logger.warning(
                "SMTP 未配置（debug 模式降级）：验证码不发送 | to={} purpose={} code={}",
                to_email,
                purpose,
                code,
            )
            return
        logger.error("SMTP 未配置，无法发送验证码邮件（release 模式）")
        raise BizError(ErrorCode.INTERNAL_ERROR, "发送邮箱验证码失败")

    def _build_message(self, to_email: str, subject: str, intro: str, code: str) -> EmailMessage:
        """拼邮件。

        Args:
            to_email: 收件人。
            subject: 主题。
            intro: 导语。
            code: 验证码。

        Returns:
            待发送的邮件对象。
        """
        body = (
            f"{intro}\n\n"
            f"    {code}\n\n"
            "验证码 5 分钟内有效，请勿泄露给他人。\n"
            "如果这不是你本人的操作，忽略本邮件即可。\n"
        )
        message = EmailMessage()
        # 发件人显示名带站点名，收件箱里比裸地址可信
        message["From"] = formataddr((self._settings.app.name, self._smtp.username))
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        return message

    async def send_email_change_link(self, to_email: str, link: str, expire_minutes: int) -> None:
        """发送换绑邮箱的确认链接。

        与验证码邮件分开：这里要带一个可点击的 URL，
        纯文本邮件里裸链接大多数客户端会自动识别为可点。

        Args:
            to_email: 新邮箱地址。
            link: 完整确认链接（含 token）。
            expire_minutes: 有效期分钟数，写进正文提醒用户。

        Raises:
            BizError: 500 发送失败。
        """
        if not self.is_configured:
            if self._settings.is_debug:
                logger.warning(
                    "SMTP 未配置（debug 降级）：确认链接不发送 | to={} link={}", to_email, link
                )
                return
            logger.error("SMTP 未配置，无法发送确认邮件（release 模式）")
            raise BizError(ErrorCode.INTERNAL_ERROR, "给新邮箱发送邮件失败")

        body = (
            "你正在申请修改博客账号的绑定邮箱。\n\n"
            f"请点击下面的链接完成确认（{expire_minutes} 分钟内有效）：\n\n"
            f"{link}\n\n"
            "如果这不是你本人的操作，忽略本邮件即可，邮箱不会变更。\n"
        )
        message = EmailMessage()
        message["From"] = formataddr((self._settings.app.name, self._smtp.username))
        message["To"] = to_email
        message["Subject"] = "确认修改绑定邮箱"
        message.set_content(body)

        try:
            await to_thread.run_sync(self._send_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("发送确认邮件失败 to={}：{}", to_email, exc)
            raise BizError(ErrorCode.INTERNAL_ERROR, "给新邮箱发送邮件失败") from exc

        logger.info("确认邮件已发送 to={}", to_email)

    def _send_sync(self, message: EmailMessage) -> None:
        """在线程池里执行的同步发送。

        587 端口的标准流程：建立连接 → STARTTLS 升级为加密 → 登录 → 发送。
        没开 STARTTLS 直接 login 会被 QQ 邮箱拒绝。

        Args:
            message: 待发送邮件。
        """
        with smtplib.SMTP(self._smtp.host, self._smtp.port, timeout=15) as server:
            server.starttls()
            server.login(self._smtp.username, self._smtp.password.get_secret_value())
            server.send_message(message)
