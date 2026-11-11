"""关于页的请求 / 响应模型。

`git_hub` 是历史拼写（带下划线），不是 `github` —— DB 列名、接口字段名、
前端取值三处都这么写。改名等于前端白屏。
"""

from pydantic import BaseModel, Field


class AboutResponse(BaseModel):
    """关于页数据。

    `abouts` 表为空时这 6 个文字字段返回 `""`（不是 null），
    只有「连管理员账号都没有」才 404。
    """

    admin_name: str
    avatar_url: str
    email: str
    introduction: str
    tech_stack: str
    my_story: str
    why: str
    interest: str
    git_hub: str  # noqa: N815 - 契约字段名，历史拼写
    csdn: str


class AboutUpdateRequest(BaseModel):
    """部分更新。

    全是 `str | None`：不传 / 传 null = 不修改。
    与用户资料的「三态」不同 —— 这里没有「清空」语义，
    想清空就传空字符串 `""`（它会被当成有效值写入）。
    """

    tech_stack: str | None = Field(default=None, max_length=255)
    my_story: str | None = None
    why: str | None = None
    interest: str | None = Field(default=None, max_length=255)
    git_hub: str | None = Field(default=None, max_length=255)
    csdn: str | None = Field(default=None, max_length=255)
