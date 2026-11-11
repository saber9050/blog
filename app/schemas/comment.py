"""评论模块的请求 / 响应模型。

时间格式是这里最容易错的地方：

- 前台评论：`2026-11-09T21:39:04.123456+08:00`（Go 的 time.Time 直接序列化）
- 后台评论：`2026-11-09T21:39:04Z`（Go 的字符串格式化，假 Z）

前端对两种都用 `new Date()` 解析，能正常工作。所以两套 DTO 分开定义，
不要「顺手统一」成一个。
"""

from pydantic import BaseModel, ConfigDict, Field


class CommentItem(BaseModel):
    """前台评论条目。

    已删除的评论也会返回，`content` 为空字符串、`is_deleted` 为 true，
    前端渲染成「该评论已删除」的占位。
    """

    id: int
    content: str
    user_id: int
    user_name: str
    avatar_url: str
    # None 或 0 都表示一级评论
    parent_id: int | None
    reply_to_name: str
    is_deleted: bool
    created_at: str
    # 一级评论的子回复总数；回复列表里恒为 0
    children_total: int


class CommentCreateRequest(BaseModel):
    """发表评论 / 回复。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, description="评论内容")
    # 回复某条一级评论时传；一级评论不传
    parent_id: int | None = None
    # 回复目标昵称快照，二级评论展示用
    reply_to_user_name: str = ""


class AdminCommentItem(BaseModel):
    """后台评论条目。

    时间格式是 `...Z`，与前台评论的 `+08:00` 不同 —— 契约如此。
    """

    id: int
    article_title: str
    user_name: str
    content: str
    created_at: str


class AdminCommentQuery(BaseModel):
    """后台评论列表查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    article_title: str = ""
    user_name: str = ""
    start_time: str = ""
    end_time: str = ""


class BatchDeleteRequest(BaseModel):
    """批量删除。空数组不报错，返回 count=0。"""

    ids: list[int] = Field(default_factory=list)


class BatchDeleteResponse(BaseModel):
    """实际删除了多少条。"""

    count: int
