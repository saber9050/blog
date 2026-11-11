"""AI 模型配置与摘要生成。

密钥全链路只进不出：
请求体（明文）→ `CryptoBox.encrypt` → 库里存密文 → 读出解密 → 调用上游。
响应里只有 `mask_key()` 处理过的前后缀。

摘要生成是唯一会真的花钱的接口，正文清洗和截断都在这里做。
"""

import re

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode
from app.core.security import CryptoBox
from app.core.timefmt import format_time_z
from app.db.models import MODEL_TYPE_CHAT, AIModelConfig
from app.integrations.llm_client import LLMClient
from app.repositories.llm_config_repository import LLMConfigRepository
from app.schemas.llm import (
    GenerateSummaryRequest,
    LLMConfigCreateRequest,
    LLMConfigResponse,
    LLMConfigUpdateRequest,
    LLMTestRequest,
    LLMTestResult,
)

# 测试连接的超时上限：用户可能把 timeout_sec 设成 60，
# 但「测一下通不通」不该让人等一分钟
TEST_TIMEOUT_CAP = 15

# 摘要输入的最大字符数。再长就截断 —— 一本 20 万字的书塞进去既慢又贵，
# 而且超出上下文窗口后上游会直接报错
SUMMARY_INPUT_LIMIT = 8000

# 摘要输出上限，与 `articles.summary` 列宽一致
SUMMARY_OUTPUT_LIMIT = 255

# HTML 标签
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Markdown 的图片与链接：`![alt](url)` / `[text](url)` 只保留文字
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# 连续空白压成一个空格
_MULTI_SPACE_RE = re.compile(r"\s+")

# 摘要用的 prompt。要求「只输出正文」是为了省掉后处理 ——
# 模型如果回「好的，这是摘要：...」，那句前缀会占掉摘要的宝贵字数
_SUMMARY_PROMPT = """请为下面的文章写一段摘要。

要求：
1. 中文，100-200 字
2. 只输出摘要正文，不要任何前缀、引号、标题或 Markdown 标记
3. 概括文章讲了什么、解决了什么问题

标题：{title}

正文：
{content}"""


class LLMService:
    """模型配置管理 + 摘要生成。"""

    def __init__(
        self,
        session: AsyncSession,
        repo: LLMConfigRepository,
        client: LLMClient,
        crypto: CryptoBox,
        settings: Settings,
    ) -> None:
        """初始化。

        Args:
            session: 数据库会话。
            repo: 配置仓储。
            client: 模型调用器。
            crypto: 密钥加解密。
            settings: 全局配置。
        """
        self._session = session
        self._repo = repo
        self._client = client
        self._crypto = crypto
        self._settings = settings

    # ============================================================
    # 配置 CRUD
    # ============================================================

    async def list_all(self) -> list[LLMConfigResponse]:
        """全部配置。`data` 直接是数组，不是分页对象。"""
        configs = await self._repo.list_all()
        return [self._to_response(c) for c in configs]

    async def get(self, config_id: int) -> LLMConfigResponse:
        """单条配置。

        Raises:
            BizError: 404 配置不存在。
        """
        config = await self._repo.find_by_id(config_id)
        if config is None:
            raise BizError(ErrorCode.NOT_FOUND, "配置不存在")
        return self._to_response(config)

    async def create(self, req: LLMConfigCreateRequest) -> LLMConfigResponse:
        """新建配置。**先测连接，通过才入库**。

        失败的配置不入库：否则后台会堆一堆连不通的条目，
        用户也分不清哪条是能用的。

        Raises:
            BizError: 400 测试连接失败。
        """
        ok, _latency, _reply, error = await self._client.test_connection(
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
            timeout_sec=TEST_TIMEOUT_CAP,
        )
        if not ok:
            raise BizError(
                ErrorCode.BAD_REQUEST, f"配置不可用，测试连接失败：{error or '未知错误'}"
            )

        config = AIModelConfig(
            base_url=req.base_url,
            # 入库前加密。明文只在内存里存在一瞬间
            api_key=self._crypto.encrypt(req.api_key),
            model=req.model,
            # 服务端强制对话模型，忽略请求体里的 type
            type=MODEL_TYPE_CHAT,
            timeout_sec=req.timeout_sec,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            status=req.status,
        )
        config_id = await self._repo.create(config)
        await self._session.refresh(config)
        await self._session.commit()

        logger.info("模型配置已创建 id={} model={}", config_id, req.model)
        return self._to_response(config)

    async def update(self, config_id: int, req: LLMConfigUpdateRequest) -> None:
        """更新运行参数。

        `base_url` / `api_key` / `model` 不可改（请求体里都没有这三个字段）。
        不传的字段取默认值（30 / 2048 / 0.3），`status` 不传则保持原值 ——
        这是 Go 版行为，前端每次都提交完整表单所以看不出来。

        Raises:
            BizError: 404 配置不存在。
        """
        config = await self._repo.find_by_id(config_id)
        if config is None:
            raise BizError(ErrorCode.NOT_FOUND, "配置不存在")

        fields: dict[str, object] = {
            "timeout_sec": req.timeout_sec if req.timeout_sec is not None else 30,
            "max_tokens": req.max_tokens if req.max_tokens is not None else 2048,
            "temperature": req.temperature if req.temperature is not None else 0.3,
        }
        if req.status is not None:
            fields["status"] = req.status

        await self._repo.update_fields(config_id, **fields)
        await self._session.commit()
        logger.info("模型配置已更新 id={} fields={}", config_id, list(fields))

    async def delete(self, config_id: int) -> None:
        """删除配置（物理删除）。

        Raises:
            BizError: 404 配置不存在。
        """
        config = await self._repo.find_by_id(config_id)
        if config is None:
            raise BizError(ErrorCode.NOT_FOUND, "配置不存在")

        await self._repo.delete(config_id)
        await self._session.commit()
        logger.info("模型配置已删除 id={}", config_id)

    # ============================================================
    # 测试连接
    # ============================================================

    async def test(self, req: LLMTestRequest) -> LLMTestResult:
        """测试连接。**永远返回 200**，成败看 `ok`。

        `api_key` 留空且传了 `id` 时复用已存密钥 ——
        用户改超时时间不该被迫重填密钥。

        Raises:
            BizError: 404 传了 id 但配置不存在，或需要复用密钥却没有密钥。
        """
        api_key = req.api_key
        if not api_key and req.id:
            config = await self._repo.find_by_id(req.id)
            if config is None:
                raise BizError(ErrorCode.NOT_FOUND, "配置不存在")
            api_key = self._crypto.decrypt(config.api_key)

        if not api_key:
            raise BizError(ErrorCode.BAD_REQUEST, "请提供 api_key")

        timeout = min(req.timeout_sec or TEST_TIMEOUT_CAP, TEST_TIMEOUT_CAP)
        ok, latency, reply, error = await self._client.test_connection(
            base_url=req.base_url,
            api_key=api_key,
            model=req.model,
            timeout_sec=timeout,
        )
        return LLMTestResult(ok=ok, latency_ms=latency, reply=reply, error=error)

    # ============================================================
    # 摘要
    # ============================================================

    async def generate_summary(self, req: GenerateSummaryRequest) -> str:
        """生成文章摘要。**不落库**。

        Raises:
            BizError: 404 配置不存在 / 400 配置禁用、正文为空 / 500 调用失败。
        """
        config = await self._repo.find_by_id(req.config_id)
        if config is None:
            raise BizError(ErrorCode.NOT_FOUND, "配置不存在")
        if config.status == 0:
            raise BizError(ErrorCode.BAD_REQUEST, "该模型配置已禁用，请先在「AI 模型」页启用")

        plain = self.strip_markup(req.content)
        if not plain:
            raise BizError(ErrorCode.BAD_REQUEST, "文章内容为空")

        # 截断放在清洗之后：HTML 标签不算正文，先洗再截能多塞点真内容
        if len(plain) > SUMMARY_INPUT_LIMIT:
            plain = plain[:SUMMARY_INPUT_LIMIT]
            logger.debug("摘要输入已截断到 {} 字符", SUMMARY_INPUT_LIMIT)

        prompt = _SUMMARY_PROMPT.format(title=req.title, content=plain)
        raw = await self._client.chat(
            base_url=config.base_url,
            api_key=self._crypto.decrypt(config.api_key),
            model=config.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            timeout_sec=config.timeout_sec,
        )

        summary = self._clean_summary(raw)
        logger.info("摘要已生成 config_id={} 长度={}", req.config_id, len(summary))
        return summary

    @staticmethod
    def strip_markup(content: str) -> str:
        """清洗正文：去 HTML 标签、去 Markdown 图片链接、压缩空白。

        为什么要洗：把 HTML 标签原样喂给模型，白花 token 还干扰理解。
        `![图](url)` 这种图片标记对摘要没有任何信息量，直接丢掉；
        `[文字](url)` 保留文字。

        Args:
            content: 原始正文。

        Returns:
            纯文本，可能为空字符串。
        """
        text = _MD_IMAGE_RE.sub("", content)
        text = _MD_LINK_RE.sub(r"\1", text)
        text = _HTML_TAG_RE.sub(" ", text)
        return _MULTI_SPACE_RE.sub(" ", text).strip()

    @staticmethod
    def _clean_summary(raw: str) -> str:
        """清洗模型返回的摘要。

        模型很爱自作主张加引号或「摘要：」前缀，这里剥掉。
        截断到 255 与 `articles.summary` 列宽对齐 —— 超了会在入库时被 MySQL
        静默截断（或报错），不如在这里明确截断。

        Args:
            raw: 模型原文。

        Returns:
            可直接入库的摘要。
        """
        text = raw.strip()
        # 去掉成对的引号（中英文都算）
        for pair in (('"', '"'), ("'", "'"), ("「", "」"), ("“", "”")):
            if text.startswith(pair[0]) and text.endswith(pair[1]) and len(text) > 1:
                text = text[1:-1].strip()
        # 去掉常见前缀
        for prefix in ("摘要：", "摘要:", "总结：", "总结:"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
        return text[:SUMMARY_OUTPUT_LIMIT]

    # ============================================================
    # 工具
    # ============================================================

    def _to_response(self, config: AIModelConfig) -> LLMConfigResponse:
        """转成响应对象，密钥脱敏。

        Args:
            config: 配置实体。

        Returns:
            响应 DTO，`api_key_masked` 形如 `sk-****cdef`。
        """
        return LLMConfigResponse(
            id=config.id,
            base_url=config.base_url,
            api_key_masked=self.mask_key(self._crypto.decrypt(config.api_key)),
            model=config.model,
            type=config.type,
            timeout_sec=config.timeout_sec,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            status=config.status,
            created_at=format_time_z(config.created_at),
            updated_at=format_time_z(config.updated_at),
        )

    @staticmethod
    def mask_key(key: str) -> str:
        """密钥脱敏。

        规则照抄 Go 的 `maskKey`：

        - 空串 → `""`
        - 长度 ≤ 4 → `****`
        - 其他 → 前 3 位 + `****` + 后 4 位

        注意是**前 3** 不是前 4，阈值是 4 不是 12。
        `sk-1234567890abcdef` → `sk-****cdef`。

        Args:
            key: 明文密钥。

        Returns:
            脱敏串。
        """
        if not key:
            return ""
        if len(key) <= 4:
            return "****"
        return f"{key[:3]}****{key[-4:]}"
