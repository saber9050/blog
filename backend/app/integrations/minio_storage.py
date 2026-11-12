"""MinIO 对象存储封装。

存进数据库的永远是**对象键**（如 `all/20261110/a1b2c3.jpg`），不是完整 URL。
只有返回给前端时才拼成完整地址。

理由：换域名、换 bucket、上 CDN 时只需改配置，不用全表 UPDATE。
Go 版就是这么做的，`GetFileURL` / `ParseFileKey` 两个方法的语义在这里复刻。
"""

import io
from functools import partial

from anyio import to_thread
from loguru import logger
from minio import Minio
from minio.error import S3Error

from app.core.config import Settings
from app.core.errors import BizError, ErrorCode


class MinioStorage:
    """对象存储。

    `minio` SDK 是**同步**的，直接在协程里调用会阻塞事件循环
    （一张 5 MB 的图上传要几百毫秒，期间整个 worker 都卡住）。
    所以每个操作都用 `anyio.to_thread.run_sync` 丢到线程池。
    """

    def __init__(self, settings: Settings) -> None:
        """创建客户端。

        Args:
            settings: 从里面取 endpoint / 凭证 / bucket / 公网地址。
        """
        self._bucket = settings.minio.bucket
        self._public_url = settings.minio.public_url.rstrip("/")
        self._client = Minio(
            endpoint=settings.minio.endpoint,
            access_key=settings.minio.access_key,
            secret_key=settings.minio.secret_key.get_secret_value(),
            secure=settings.minio.use_ssl,
        )

    async def ensure_bucket(self) -> bool:
        """确保 bucket 存在，不存在则创建。

        启动时调用一次。失败只打警告不阻断启动：
        图片功能不可用，但登录、文章、评论照常。

        注意异常捕获范围：minio SDK 在网络不通时抛的是
        `urllib3.exceptions.MaxRetryError` / `ProtocolError`，**不是** `S3Error`，
        只捕 S3Error 会让「本地没起 MinIO」直接导致整个应用启不来。
        """
        try:
            exists = await to_thread.run_sync(partial(self._client.bucket_exists, self._bucket))
            if not exists:
                await to_thread.run_sync(partial(self._client.make_bucket, self._bucket))
                logger.info("MinIO bucket 已创建：{}", self._bucket)
            return True
        except S3Error as exc:
            # 服务端连上了但拒绝了请求（权限、bucket 名非法等）
            logger.error("MinIO bucket 检查失败（bucket={}）：{}", self._bucket, exc)
            return False
        except Exception as exc:  # noqa: BLE001 - 启动探活要吞掉一切，避免整站起不来
            logger.error(
                "MinIO 不可用（endpoint={}），图片上传功能将不可用：{}: {}",
                self._client._base_url,
                type(exc).__name__,
                exc,
            )
            return False

    # ---------- SupportsFileStorage 实现 ----------

    async def upload(self, object_name: str, data: bytes, content_type: str) -> str:
        """上传文件。

        Args:
            object_name: 对象键，如 `all/20261110/a1b2c3.jpg`。
            data: 文件内容。
            content_type: MIME 类型，如 `image/jpeg`。

        Returns:
            对象键（与入参相同）。

        Raises:
            BizError: 500 上传失败。
        """
        try:
            await to_thread.run_sync(
                partial(
                    self._client.put_object,
                    self._bucket,
                    object_name,
                    io.BytesIO(data),
                    length=len(data),
                    content_type=content_type,
                )
            )
            return object_name
        except (S3Error, OSError) as exc:
            logger.error("MinIO 上传失败 key={}：{}", object_name, exc)
            raise BizError(ErrorCode.INTERNAL_ERROR, "上传图片失败") from exc

    async def delete(self, object_name: str) -> None:
        """删除对象。

        **失败不抛异常**：调用场景是「删文章时顺手清理图片」，
        图片删不掉不该让文章删不掉。失败只记日志，方便后续人工清理孤儿文件。

        Args:
            object_name: 对象键。空串直接返回。
        """
        if not object_name:
            return
        try:
            await to_thread.run_sync(partial(self._client.remove_object, self._bucket, object_name))
        except (S3Error, OSError) as exc:
            logger.warning("MinIO 删除失败 key={}（可能是孤儿文件，可忽略）：{}", object_name, exc)

    def public_url(self, object_name: str) -> str:
        """对象键 → 完整访问 URL。

        Args:
            object_name: 对象键。空串返回空串（接口里对应 `""`）。

        Returns:
            形如 `https://zouxp.xyz/blog-project/all/20261110/a1b2c3.jpg`。

        注意：这里拼的是 `{base_url}/{bucket}/{key}`。
        生产环境 Nginx 会把 `/blog-project/` 反代到 MinIO，
        `MINIO_PUBLIC_URL` 必须是纯源（如 `https://zouxp.xyz`），
        带路径前缀会导致封面 403 —— 这是 Go 版踩过的坑。
        """
        if not object_name:
            return ""
        # 已经是完整 URL 就不再拼（兼容前端可能直接传 URL 的情况）
        if object_name.startswith(("http://", "https://")):
            return object_name
        return f"{self._public_url}/{self._bucket}/{object_name.lstrip('/')}"

    def parse_key(self, url: str) -> str:
        """完整 URL → 对象键。

        写入数据库前必须转成 key。解析失败的常见原因是
        `MINIO_PUBLIC_URL` 配错（比如末尾多了斜杠、少了 bucket 段），
        这种情况要报错而不是把错值存进去。

        Args:
            url: 完整 URL，或本来就是 key 的字符串。

        Returns:
            对象键。

        Raises:
            BizError: 500 URL 不属于当前存储，无法解析。
        """
        if not url:
            return ""
        # 已经是 key（不含协议）就直接用
        if not url.startswith(("http://", "https://")):
            return url.lstrip("/")

        prefix = f"{self._public_url}/{self._bucket}/"
        if url.startswith(prefix):
            return url[len(prefix) :]

        # 兜底：按 bucket 段切一次，兼容域名换过但 bucket 没变的历史数据
        marker = f"/{self._bucket}/"
        idx = url.find(marker)
        if idx >= 0:
            return url[idx + len(marker) :]

        logger.error("无法解析图片 URL：{}（请检查 MINIO_PUBLIC_URL 配置）", url)
        raise BizError(ErrorCode.INTERNAL_ERROR, "解析url失败")
