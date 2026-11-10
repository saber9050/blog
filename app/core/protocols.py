"""跨模块契约（Protocol）。

为什么用 `Protocol` 而不是抽象基类（ABC）：

- 业务代码只依赖「能力」，不依赖「继承关系」。auth 模块只关心「能存能取」，
  不关心背后是 Redis 还是内存字典。
- 单测可以塞一个 20 行的内存实现，不用起 Redis、不用 mock 第三方库。
- Python 的 Protocol 是结构化类型，实现方不需要显式 `class X(SupportsCache)`，
  少一层耦合。

不用 ABC 的原因更直接：Python 没有 Java 那样的强约束，
多一层继承只会让「我想换个实现」变成「得改继承树」。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SupportsCache(Protocol):
    """键值缓存能力的最小契约。

    方法名刻意用最朴素的 get / set / delete，
    不要做成 `get_json` / `set_with_ttl_and_prefix` 这种带业务语义的接口 ——
    那样缓存实现就得知道业务规则了。
    """

    async def get(self, key: str) -> str | None:
        """读字符串。不存在返回 None。"""
        ...

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        """写字符串，可指定过期秒数。"""
        ...

    async def delete(self, key: str) -> None:
        """删除键。键不存在不报错。"""
        ...

    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        """仅当键不存在时写入（原子）。

        Returns:
            True 表示写入成功（键原本不存在），
            False 表示键已存在（用于发信频率限制这类「60 秒内只能一次」的场景）。
        """
        ...


@runtime_checkable
class SupportsFileStorage(Protocol):
    """对象存储能力的最小契约。"""

    async def upload(self, object_name: str, data: bytes, content_type: str) -> str:
        """上传文件。

        Args:
            object_name: 对象键（如 `all/20261110/ab12.jpg`），不含 bucket。
            data: 文件字节。
            content_type: MIME 类型。

        Returns:
            实际写入的对象键（与入参一致，便于调用方直接入库）。
        """
        ...

    async def delete(self, object_name: str) -> None:
        """删除对象。对象不存在时**不抛异常**（删文章时可能重复清理）。"""
        ...

    def public_url(self, object_name: str) -> str:
        """把对象键拼成浏览器可访问的完整 URL。

        Args:
            object_name: 对象键。传空串返回空串。

        Returns:
            形如 `https://zouxp.xyz/blog-project/all/20261110/ab12.jpg`。
        """
        ...

    def parse_key(self, url: str) -> str:
        """从完整 URL 里反解出对象键。

        新建/更新文章时前端传的是完整 URL，入库要存 key。
        解析失败抛 `BizError`（500），不要静默存个错值进去。

        Args:
            url: 完整 URL 或已经是 key 的字符串。

        Returns:
            对象键。
        """
        ...
