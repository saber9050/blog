"""用户模块的请求 / 响应模型。

两个「必须照抄的错误拼写」：

- `UserInfoResponse.staus`（应为 status）
- `UserInfoResponse.create_at`（应为 created_at）

前端已按这两个名字取值，改名等于线上白屏。
这不是疏漏，是契约 —— 想改就得连前端一起改，且要处理灰度期。
"""

from pydantic import BaseModel, ConfigDict, Field


class UpdateProfileRequest(BaseModel):
    """编辑资料。

    字段类型是 `str | None`，语义按「三态」区分：

    | 传值 | 含义 |
    |---|---|
    | 不传 / `null` | 不修改 |
    | `""` | 清空该字段 |
    | 有内容 | 改成新值 |

    Go 版用 `!= ""` 判断，导致「传 `""` 想清空」被当成「不修改」，
    简介永远清不掉。这里用 `None` 与 `""` 区分开。
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    nick_name: str | None = Field(default=None, max_length=15, description="昵称")
    introduction: str | None = Field(default=None, description="个人简介")


class UpdatePasswordRequest(BaseModel):
    """修改密码。"""

    old_password: str = Field(description="当前密码")
    new_password: str = Field(description="新密码，11-20 位含字母和数字")
    ack: str = Field(description="新密码二次确认")


class UpdateEmailRequest(BaseModel):
    """申请换绑邮箱。

    `captcha` 是发到**当前**邮箱的验证码（purpose=reset_email），
    用来证明「操作者是本人」；新邮箱的归属由第二段确认链接证明。
    """

    password: str = Field(description="当前密码")
    captcha: str = Field(description="6 位验证码，发到当前邮箱")
    new_email: str = Field(description="新邮箱")


class AddEmailRequest(BaseModel):
    """首次补绑邮箱。直接生效，不发确认邮件。"""

    new_email: str = Field(description="要绑定的邮箱")
    captcha: str = Field(description="6 位验证码（purpose=add_email）")


class UserInfoResponse(BaseModel):
    """我的资料。

    ⚠️ `staus` 与 `create_at` 是历史拼写错误，**不要"顺手修正"**。
    """

    user_id: int
    user_name: str
    account: str
    email: str
    avatar_url: str
    introduction: str
    role_id: int
    staus: int  # noqa: RUF001 - 契约字段名，拼写错误但必须保留
    create_at: str  # 同上


class UpdateAvatarResponse(BaseModel):
    """头像上传结果。"""

    avatar_url: str


class AdminCreateUserRequest(BaseModel):
    """后台创建用户。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    user_name: str = Field(min_length=1, max_length=15)
    account: str
    password: str
    status: int = Field(ge=0, le=1, description="1 启用 / 0 禁用")


class AdminUpdateUserRequest(BaseModel):
    """后台启用 / 禁用。"""

    status: int = Field(ge=0, le=1)


class AdminUserItem(BaseModel):
    """后台列表里的一行。"""

    id: int
    user_name: str
    avatar_url: str
    status: int
    created_at: str


class AdminUserListResponse(BaseModel):
    """后台用户列表。

    ⚠️ 分页字段是 `pageSize`（驼峰），与其他模块的 `page_size` 不一致。
    这是 Go 版的历史遗留，前端按驼峰取值，不能统一。
    """

    list: list[AdminUserItem]
    total: int
    page: int
    pageSize: int  # noqa: N815 - 驼峰是契约要求


class AdminUserQuery(BaseModel):
    """后台列表的查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    keyword: str = ""
    status: int | None = None
    start_time: str = ""
    end_time: str = ""


class AdminCreateUserResponse(BaseModel):
    """后台创建用户的返回：只有 ID。"""

    id: int


class IsExistsResponse(BaseModel):
    """邮箱唯一性检测。"""

    is_exists: bool


class MessageResponse(BaseModel):
    """只带一句提示。"""

    message: str
