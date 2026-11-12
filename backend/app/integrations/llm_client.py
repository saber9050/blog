"""OpenAI 兼容协议的大模型调用。

只实现 `POST {base_url}/chat/completions` 这一个端点 ——
DeepSeek / 通义 / Moonshot / OpenAI 都用这个协议，一套代码通吃。

不用官方 SDK：`openai` 包对 base_url 的处理有版本差异，而且它自带重试和
流式解析，我们只需要「发一条消息、拿一条回复」。httpx 二十行就够。
"""

import time
from typing import Any

import httpx
from loguru import logger

from app.core.errors import BizError, ErrorCode

# 测试连接时用的固定 prompt。要求它只回四个字，方便前端展示「连接成功」
_TEST_PROMPT = '请只回复"连接成功"四个字，不要加任何标点和解释。'


class LLMClient:
    """对话模型调用器。

    无状态：每次调用都传完整配置，不缓存 client 实例 ——
    配置可能在后台被改，缓存会导致用了旧密钥。
    """

    async def chat(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
        timeout_sec: int = 30,
    ) -> str:
        """发起一次对话调用。

        Args:
            base_url: 到 `/v1` 为止的基址。
            api_key: 明文密钥（调用前才解密，不落日志）。
            model: 模型 ID。
            messages: OpenAI 格式的消息列表。
            max_tokens: 生成上限。
            temperature: 采样温度。
            timeout_sec: 超时秒数。

        Returns:
            模型回复的正文。

        Raises:
            BizError: 500 超时 / 网络错误 / 上游返回非 2xx。
        """
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # 不流式：摘要是一次性拿到全文再填进编辑器，流式没有意义
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("模型调用超时 base_url={} model={}", base_url, model)
            raise BizError(ErrorCode.INTERNAL_ERROR, f"调用模型超时（{timeout_sec}s）") from exc
        except httpx.HTTPError as exc:
            logger.warning("模型调用网络错误 base_url={}：{}", base_url, exc)
            raise BizError(ErrorCode.INTERNAL_ERROR, "调用模型失败：网络错误") from exc

        if response.status_code != 200:
            raise BizError(
                ErrorCode.INTERNAL_ERROR,
                f"LLM 返回异常状态码 {response.status_code}: {self._extract_error(response)}",
            )

        return self._extract_content(response)

    async def test_connection(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: int = 15,
    ) -> tuple[bool, int, str | None, str | None]:
        """测试连接。

        与 `chat` 的区别：**失败不抛异常**，把错误信息作为返回值。
        前端需要区分「连不通」和「服务器挂了」——前者是正常业务结果。

        Args:
            base_url: API 基址。
            api_key: 明文密钥。
            model: 模型 ID。
            timeout_sec: 超时秒数（调用方已把它截到 15 秒以内）。

        Returns:
            `(ok, latency_ms, reply, error)`。
        """
        start = time.perf_counter()
        try:
            reply = await self.chat(
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=[{"role": "user", "content": _TEST_PROMPT}],
                # 测试不求长回复，给 32 个 token 足够
                max_tokens=32,
                temperature=0,
                timeout_sec=timeout_sec,
            )
        except BizError as exc:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency, None, exc.message

        latency = int((time.perf_counter() - start) * 1000)
        return True, latency, reply, None

    @staticmethod
    def _extract_error(response: httpx.Response) -> str:
        """从上游的错误响应里取一句话。

        只取 `error.message`，不返回完整响应体 ——
        完整体里可能带 base_url、内部路由等结构信息。

        Args:
            response: 上游响应。

        Returns:
            错误描述。解析失败时返回状态的原文片段。
        """
        try:
            body = response.json()
        except ValueError:
            return response.text[:200] or "未知错误"

        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        if isinstance(error, str):
            return error[:300]
        return str(body)[:300]

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        """从正常响应里取回复正文。

        Args:
            response: 上游响应。

        Returns:
            消息正文。

        Raises:
            BizError: 500 响应结构不符合预期。
        """
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.error("模型响应结构异常：{}", response.text[:300])
            raise BizError(ErrorCode.INTERNAL_ERROR, "模型返回格式异常") from exc

        return str(content or "").strip()
