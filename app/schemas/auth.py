"""认证模块的请求 / 响应模型。

字段名严格照抄 Go 版契约，几个容易写错的点：

- 登录响应用 `user_role_id`，不是 `role_id`
- 图形验证码响应用 `base_64`（带下划线），不是 `base64`
- 注册 / 改密成功返回 `{"message": "xxx"}`，不是空 data

⚠️ 这里**只做格式校验**（类型、长度、必填）。
「密码必须同时含字母和数字」这类规则属于业务规则，放在 service 层 ——
否则单测要绕 HTTP 层才能验证，而且换个入口（比如后台改密）就得复制一遍。
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 邮箱验证码的用途。用 Literal 而不是 str：
# 传错值时 FastAPI 直接返回 400，不用在 service 里再判一次
CaptchaPurpose = Literal["login", "reset_password", "reset_email", "add_email"]

# 账号：11 位纯数字
_ACCOUNT_RE = re.compile(r"^\d{11}$")

# 密码：11-20 位，只允许字母数字，且必须同时包含字母和数字。
# 用两个前瞻断言，比写两遍 `if not any(...)` 更紧凑
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{11,20}$")


def is_valid_account(account: str) -> bool:
    """账号格式：11 位纯数字。

    Args:
        account: 待校验账号。

    Returns:
        是否合法。
    """
    return bool(_ACCOUNT_RE.fullmatch(account))


def is_valid_password(password: str) -> bool:
    """密码格式：11-20 位、纯字母数字、必须同时含字母和数字。

    Args:
        password: 待校验密码。

    Returns:
        是否合法。
    """
    return bool(_PASSWORD_RE.fullmatch(password))


class RegisterRequest(BaseModel):
    """注册请求。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    user_name: str = Field(min_length=1, max_length=15, description="昵称，全局唯一")
    account: str = Field(description="账号，11 位纯数字")
    password: str = Field(description="密码，11-20 位，含字母和数字")
    ack: str = Field(description="密码二次确认")


class LoginRequest(BaseModel):
    """账号密码登录请求。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    account: str = Field(description="账号")
    password: str = Field(description="密码")
    captcha_key: str = Field(description="图形验证码的 captcha_id")
    captcha_code: str = Field(description="用户输入的 6 位验证码")


class EmailLoginRequest(BaseModel):
    """邮箱验证码登录请求。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(description="账号绑定的邮箱")
    purpose: Literal["login"] = Field(default="login", description="固定 login")
    captcha: str = Field(description="邮箱收到的 6 位验证码")


class SendEmailCaptchaRequest(BaseModel):
    """发送邮箱验证码请求。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(description="接收邮箱")
    purpose: CaptchaPurpose = Field(description="用途")


class ResetPasswordRequest(BaseModel):
    """邮箱验证码重置密码请求。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(description="注册邮箱")
    captcha: str = Field(description="验证码（purpose=reset_password）")
    new_password: str = Field(description="新密码")
    ack: str = Field(description="新密码二次确认")


class LoginResponse(BaseModel):
    """登录成功响应。

    **不含 refresh_token**：它藏在 access token 的 `tid` claim 里，不对外暴露。
    这样即使 XSS 拿到响应，也拿不到 72 小时有效的长期凭证。
    """

    user_name: str
    user_id: int
    user_role_id: int
    access_token: str


class RefreshTokenResponse(BaseModel):
    """刷新令牌响应。"""

    access_token: str


class ImageCaptchaResponse(BaseModel):
    """图形验证码响应。"""

    # 注意是 base_64 不是 base64，前端已按这个名字取值
    captcha_id: str
    base_64: str


class IsExistsResponse(BaseModel):
    """唯一性检测响应。"""

    is_exists: bool


class MessageResponse(BaseModel):
    """只带一句提示的响应体。

    对应 Go 版的 `gin.H{"message": "注册成功"}`。
    前端可能读 `data.message` 弹 toast，所以不能简化成空 data。
    """

    message: str
