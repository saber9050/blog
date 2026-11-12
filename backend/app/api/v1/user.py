"""个人中心接口（前台 8 条）。

`/user/email` 这一条比较特殊：它是邮件里的确认链接，用户点开时浏览器
不带 Authorization 头，所以**不能**挂登录依赖，且返回 HTML 而不是 JSON。
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.deps import CurrentUser, get_current_user, get_user_service
from app.core.errors import BizError
from app.core.pages import render_result_page
from app.core.response import ResponseBuilder
from app.schemas.user import (
    AddEmailRequest,
    UpdateEmailRequest,
    UpdatePasswordRequest,
    UpdateProfileRequest,
)
from app.services.user.user_service import UserService


class UserController:
    """个人中心。

    无状态：service 通过 `Depends` 注入，不存成实例属性。
    """

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(prefix="/user", tags=["用户"])
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        顺序遵循「静态路径在前」：本模块全是静态路径，没有 `{id}`，
        顺序不影响匹配，但保持规范。
        """
        r = self.router
        r.add_api_route("/info", self.get_info, methods=["GET"], summary="我的资料")
        r.add_api_route("/profile", self.update_profile, methods=["POST"], summary="编辑资料")
        r.add_api_route("/avatar", self.update_avatar, methods=["POST"], summary="上传头像")
        r.add_api_route("/password", self.update_password, methods=["POST"], summary="修改密码")
        r.add_api_route(
            "/email_ack", self.request_email_change, methods=["POST"], summary="申请换绑邮箱"
        )
        r.add_api_route("/add_email", self.add_email, methods=["POST"], summary="首次补绑邮箱")
        r.add_api_route(
            "/is_exists_email",
            self.is_exists_email,
            methods=["GET"],
            summary="邮箱唯一性检测",
        )
        # ⚠️ 这一条不加登录依赖：邮件链接直达，浏览器不会带 Authorization
        r.add_api_route("/email", self.confirm_email, methods=["GET"], summary="确认换绑邮箱")

    # ============================================================
    # 资料
    # ============================================================

    async def get_info(
        self,
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """我的资料。"""
        result = await service.get_info(current.user_id)
        return ResponseBuilder.ok(result)

    async def update_profile(
        self,
        req: UpdateProfileRequest,
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """编辑昵称与简介。"""
        await service.update_profile(current.user_id, req)
        return ResponseBuilder.ok(None)

    async def update_avatar(
        self,
        file: UploadFile = File(description="头像图片"),
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """上传头像。字段名是 `file`，前端 FormData 要对应。"""
        avatar_url = await service.update_avatar(current.user_id, file)
        return ResponseBuilder.ok({"avatar_url": avatar_url})

    async def update_password(
        self,
        req: UpdatePasswordRequest,
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """修改密码。"""
        await service.update_password(current.user_id, req)
        return ResponseBuilder.ok(None)

    # ============================================================
    # 邮箱
    # ============================================================

    async def request_email_change(
        self,
        req: UpdateEmailRequest,
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """申请换绑邮箱：只发确认邮件，不改库。"""
        await service.request_email_change(current.user_id, req)
        return ResponseBuilder.ok({"message": "已发送确认邮件到新邮箱，请到邮箱确认"})

    async def add_email(
        self,
        req: AddEmailRequest,
        current: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """首次补绑邮箱：直接生效。"""
        await service.add_email(current.user_id, req)
        return ResponseBuilder.ok({"message": "添加成功"})

    async def is_exists_email(
        self,
        new_email: str = Query(description="待检测邮箱"),
        _: CurrentUser = Depends(get_current_user),
        service: UserService = Depends(get_user_service),
    ):
        """邮箱唯一性检测。参数名是 `new_email`，不是 `email`。"""
        exists = await service.is_exists_email(new_email)
        return ResponseBuilder.ok({"is_exists": exists})

    async def confirm_email(
        self,
        token: str = Query(default="", description="邮件链接里的 JWT"),
        service: UserService = Depends(get_user_service),
    ):
        """确认换绑邮箱：浏览器落地页，返回 HTML。

        **四种情况全部 HTTP 200**，成败只体现在页面文案上。
        业务异常在这里被吃掉并转成失败页 —— 用户点链接是为了看提示，
        不是为了看一段 JSON 错误。
        """
        if not token:
            return render_result_page(
                "邮箱修改失败",
                "缺少必要的确认信息，请重新发送确认邮件",
                success=False,
            )

        try:
            await service.confirm_email(token)
        except BizError:
            # 统一文案：不区分「签名错」「过期」「已用过」。
            # 对用户来说处理方式都一样（重新申请），区分反而泄露信息
            return render_result_page(
                "邮箱修改失败",
                "确认链接无效或已过期，请重新申请修改",
                success=False,
            )

        return render_result_page(
            "邮箱修改成功",
            "您已成功修改绑定邮箱，下次登录可以使用新邮箱",
            success=True,
        )
