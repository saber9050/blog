"""文章模块的请求 / 响应模型。

`ArticleItem` 是前台列表、详情、后台列表共用的结构 ——
一个 article 的展示需要拼 6 张表的数据，结构定死了才好优化 N+1。
"""

from pydantic import BaseModel, ConfigDict, Field


class TaxonomyRef(BaseModel):
    """分类 / 标签的引用对象。

    分类被删时整体为 `null`（不是空对象），前端用 `article.category?.name` 判空。
    """

    id: int
    name: str


class ArticleItem(BaseModel):
    """通用文章条目。"""

    id: int
    title: str
    summary: str
    cover_url: str
    status: int
    views: int
    like_count: int
    comment_count: int
    is_liked: bool
    author_name: str
    category: TaxonomyRef | None
    tags: list[TaxonomyRef]
    created_at: str


class ArticleDetail(ArticleItem):
    """文章详情：在列表结构上加正文。"""

    content: str


class AdminArticleItem(ArticleItem):
    """后台列表项：多一个更新时间。"""

    updated_at: str


class ArticleListQuery(BaseModel):
    """前台列表查询参数。"""

    page: int = Field(default=1, ge=1)
    # Go 版没有上限，这里在 service 层截断到 100，schema 只做下界
    page_size: int = Field(default=10, ge=1)
    sort: str = "latest"
    category_id: int | None = None
    # 逗号分隔的标签 ID，如 "1,2,3"
    tag_ids: str = ""
    keyword: str = ""


class AdminArticleQuery(BaseModel):
    """后台列表查询参数。

    注意 `tag_id` 是**单个**，与前台的 `tag_ids`（逗号分隔）不同 ——
    两个模块的历史包袱不一样，不能统一。
    """

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    status: int | None = None
    category_id: int | None = None
    tag_id: int | None = None
    keyword: str = ""


class ArticleCreateRequest(BaseModel):
    """新建文章。"""

    model_config = ConfigDict(str_strip_whitespace=False)

    title: str = Field(min_length=1, max_length=200)
    type_id: int = Field(description="分类 ID")
    tag_ids: list[int] = Field(default_factory=list)
    # 完整 URL，后端负责转成 object key
    cover_url: str = ""
    summary: str = Field(default="", max_length=255)
    content: str = Field(min_length=1)
    status: int = Field(ge=0, le=1)


class ArticleUpdateRequest(BaseModel):
    """更新文章。

    所有字段可选 —— 传了才更新，不传保持原值。
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    title: str | None = Field(default=None, max_length=200)
    type_id: int | None = None
    tag_ids: list[int] | None = None
    cover_url: str | None = None
    summary: str | None = Field(default=None, max_length=255)
    content: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)


class ArticleTransferRequest(BaseModel):
    """批量转移分类。"""

    from_type_id: int
    to_type_id: int


class SiteStatsResponse(BaseModel):
    """站点统计。"""

    article_count: int
    total_views: int
    total_likes: int


class RandomArticleResponse(BaseModel):
    """随机文章只返回 ID，前端自己跳转。"""

    id: int


class ArticleIdResponse(BaseModel):
    """新建文章返回的 ID。"""

    id: int


class TransferCountResponse(BaseModel):
    """转移了多少篇。"""

    count: int


class UploadResponse(BaseModel):
    """图片上传返回完整 URL。"""

    url: str
