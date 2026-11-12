"""认证接口控制器。

只做三件事：解析请求 → 调 service → 包统一响应。
**不写任何业务判断**（包括「两次密码是否一致」）—— 那种规则放 service，
否则单测要绕 HTTP 层才能验证。
"""

from fastapi import APIRouter, Depends, Header, Query

from app.core.deps import get_auth_service
from app.core.errors import BizError, ErrorCode
from app.core.response import ResponseBuilder
from app.schemas.auth import (
    EmailLoginRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SendEmailCaptchaRequest,
)
from app.services.auth.auth_service import AuthService


class AuthController:
    """认证模块的 HTTP 入口。

    无状态：service 通过 `Depends` 注入到每个方法上，而不是存成实例属性 ——
    存成属性就意味着 controller 是可变单例，多请求并发时会串数据。
    """

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(prefix="/auth", tags=["认证"])
        self._register_routes()

    def _register_routes(self) -> None:
        """把所有认证路由挂到 APIRouter 上。

        静态路径与参数路径不冲突（本模块没有 `/{id}`），
        顺序不影响匹配，但仍按「先静态后动态」的规范排列。
        """
        router = self.router

        router.add_api_route("/register", self.register, methods=["POST"], summary="注册")
        router.add_api_route("/login", self.login, methods=["POST"], summary="账号密码登录")
        router.add_api_route(
            "/email_login", self.email_login, methods=["POST"], summary="邮箱验证码登录"
        )
        router.add_api_route(
            "/image_captcha", self.image_captcha, methods=["GET"], summary="获取图形验证码"
        )
        router.add_api_route(
            "/captcha", self.send_email_captcha, methods=["POST"], summary="发送邮箱验证码"
        )
        router.add_api_route(
            "/reset_password", self.reset_password, methods=["POST"], summary="重置密码"
        )
        router.add_api_route("/refresh", self.refresh, methods=["POST"], summary="刷新令牌")
        router.add_api_route("/logout", self.logout, methods=["POST"], summary="登出")
        router.add_api_route(
            "/is_exists_name", self.is_exists_name, methods=["GET"], summary="昵称唯一性检测"
        )
        router.add_api_route(
            "/is_exists_account",
            self.is_exists_account,
            methods=["GET"],
            summary="账号唯一性检测",
        )

    # ============================================================
    # 接口实现
    # ============================================================

    async def register(
        self,
        req: RegisterRequest,
        service: AuthService = Depends(get_auth_service),
    ):
        """注册。

        `data` 里带 `message` 是 Go 版的原始结构，前端可能读它弹提示，
        不能简化成空 data。
        """
        await service.register(req)
        return ResponseBuilder.ok({"message": "注册成功"})

    async def login(
        self,
        req: LoginRequest,
        service: AuthService = Depends(get_auth_service),
    ):
        """账号密码登录。"""
        result = await service.login(req)
        return ResponseBuilder.ok(result)

    async def email_login(
        self,
        req: EmailLoginRequest,
        service: AuthService = Depends(get_auth_service),
    ):
        """邮箱验证码登录。"""
        result = await service.email_login(req)
        return ResponseBuilder.ok(result)

    async def image_captcha(
        self,
        service: AuthService = Depends(get_auth_service),
    ):
        """获取图形验证码（无需登录）。"""
        result = await service.send_image_captcha()
        return ResponseBuilder.ok(result)

    async def send_email_captcha(
        self,
        req: SendEmailCaptchaRequest,
        service: AuthService = Depends(get_auth_service),
    ):
        """发送邮箱验证码。"""
        await service.send_email_captcha(req)
        return ResponseBuilder.ok({"message": "已向你的邮箱发送验证码"})

    async def reset_password(
        self,
        req: ResetPasswordRequest,
        service: AuthService = Depends(get_auth_service),
    ):
        """邮箱验证码重置密码。"""
        await service.reset_password(req)
        return ResponseBuilder.ok({"message": "成功修改密码"})

    async def refresh(
        self,
        authorization: str | None = Header(default=None, alias="Authorization"),
        service: AuthService = Depends(get_auth_service),
    ):
        """刷新令牌。

        这个接口**允许 access token 已过期**，所以不能走 `get_current_user`
        （那个依赖会拒绝过期 token）。token 由这里手工解析。
        """
        token = self._extract_bearer(authorization, "请提供 Access Token")
        result = await service.refresh(token)
        return ResponseBuilder.ok(result)

    async def logout(
        self,
        authorization: str | None = Header(default=None, alias="Authorization"),
        service: AuthService = Depends(get_auth_service),
    ):
        """登出。

        幂等：没带 token、token 无效都返回成功 ——
        前端登出按钮不该因为 token 过期而弹错误框。
        """
        if authorization:
            try:
                token = self._extract_bearer(authorization, "请提供 Access Token")
                await service.logout(token)
            except BizError:
                # 解析失败也当登出成功，不向外抛
                pass
        else:
            await service.logout("")
        return ResponseBuilder.ok(None)

    async def is_exists_name(
        self,
        user_name: str = Query(description="待检测的昵称"),
        service: AuthService = Depends(get_auth_service),
    ):
        """昵称唯一性检测。参数名是 `user_name`，不是 `name`。"""
        result = await service.is_exists_name(user_name)
        return ResponseBuilder.ok(result)

    async def is_exists_account(
        self,
        account: str = Query(description="待检测的账号"),
        service: AuthService = Depends(get_auth_service),
    ):
        """账号唯一性检测。"""
        result = await service.is_exists_account(account)
        return ResponseBuilder.ok(result)

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _extract_bearer(authorization: str | None, missing_message: str) -> str:
        """从 Authorization 头里取出 Bearer token。

        Args:
            authorization: 原始请求头值。
            missing_message: 缺失时的报错文案（不同接口措辞不同，
                Go 版 refresh 用「请提供 Access Token」）。

        Returns:
            纯 token。

        Raises:
            BizError: 401 缺失或格式错误。
        """
        if not authorization:
            raise BizError(ErrorCode.UNAUTHORIZED, missing_message)

        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise BizError(ErrorCode.UNAUTHORIZED, "令牌格式错误")

        return parts[1]
