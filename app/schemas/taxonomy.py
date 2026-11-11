"""分类与标签的请求 / 响应模型。

两者结构几乎一致（名称 + 状态），共用一套 DTO；
差异只在长度上限（分类 50、标签 100）与业务规则，由 service 层处理。
"""

from pydantic import BaseModel, Field


class TaxonomyPublicItem(BaseModel):
    """前台列表项。

    字段是 `id` + `name`（不是 `category_name` / `tag_name`）——
    前端直接把 name 渲染成标签，不关心它来自哪个列。
    """

    id: int
    name: str


class TaxonomyAdminItem(BaseModel):
    """后台列表项。"""

    id: int
    name: str
    status: int
    created_at: str


class TaxonomyQuery(BaseModel):
    """后台列表查询参数。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1)
    status: int | None = None
    keyword: str = ""
    start_time: str = ""
    end_time: str = ""


class TaxonomyCreateRequest(BaseModel):
    """新建。

    名称在 service 层统一 `strip()`：MySQL 的 ci 排序规则忽略尾空格，
    不 strip 的话「后端」与「后端 」查重时算重名、存进去却是两个串。
    """

    name: str = Field(min_length=1, description="名称")
    status: int = Field(ge=0, le=1, description="1 启用 / 0 禁用")


class TaxonomyUpdateRequest(BaseModel):
    """更新。名称与状态都必填（不是局部更新）。"""

    name: str = Field(min_length=1, description="名称")
    status: int = Field(ge=0, le=1)


class CountResponse(BaseModel):
    """数量统计。"""

    count: int


class TaxonomyIdResponse(BaseModel):
    """新建后返回的 ID。"""

    id: int
