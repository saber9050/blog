"""AI 模型模块的请求 / 响应模型。

`api_key` 全链路只进不出：
- 请求体里可以传明文（新建 / 测试）
- 响应里**永远只有脱敏串** `api_key_masked`
- 库里存的是 Fernet 密文
"""

from pydantic import BaseModel, ConfigDict, Field


class LLMConfigResponse(BaseModel):
    """配置响应。

    `type` 恒为 1（对话模型），保留是因为前端表格有"类型"列。
    Go 版的 `dimension` 字段已删除（新库无此列）。
    """

    id: int
    base_url: str
    # 脱敏后的密钥，形如 sk-****cdef。明文绝不返回
    api_key_masked: str
    model: str
    type: int
    timeout_sec: int
    max_tokens: int
    temperature: float
    status: int
    created_at: str
    updated_at: str


class LLMConfigCreateRequest(BaseModel):
    """新建配置。

    `type` 不接受前端传值 —— 服务端强制 1。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: str = Field(min_length=1, description="API 基址，到 /v1 为止")
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    timeout_sec: int = Field(default=30, ge=1)
    max_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.3, ge=0, le=2)
    status: int = Field(default=1, ge=0, le=1)


class LLMConfigUpdateRequest(BaseModel):
    """更新配置。

    ⚠️ **只允许改运行参数与状态**。`base_url` / `api_key` / `model` 不可改 ——
    要换模型请删了重建，避免「改了一个字段但连接信息还是旧的」这种半吊子状态。
    """

    timeout_sec: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    status: int | None = Field(default=None, ge=0, le=1)


class LLMTestRequest(BaseModel):
    """测试连接。

    `api_key` 留空且传了 `id` 时，复用该配置已存的密钥 ——
    用户改超时时间时不该被迫重填密钥。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key: str = ""
    id: int | None = None
    timeout_sec: int | None = None


class LLMTestResult(BaseModel):
    """测试结果。

    **成功和失败都走 HTTP 200**，前端按 `ok` 判断。
    连不通是预期结果，不是服务器错误 —— 用 500 会让前端全局拦截器弹错误框。
    """

    ok: bool
    latency_ms: int
    reply: str | None = None
    error: str | None = None


class GenerateSummaryRequest(BaseModel):
    """生成摘要。

    摘要**不落库**：接口只负责生成，前端填进编辑器，用户确认后随文章保存。
    """

    config_id: int
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class SummaryResponse(BaseModel):
    """摘要文本，已去掉首尾引号并截断到 255 字符。"""

    summary: str
