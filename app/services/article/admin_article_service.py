"""后台文章管理。

继承公共查询，额外提供写操作。图片差集同步是这里最需要小心的地方 ——
删错了就是把用户的图删了。
"""

import secrets
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import func, update

from app.core.errors import BizError, ErrorCode
from app.db.base import not_deleted
from app.db.models import Article, Comment
from app.schemas.article import (
    AdminArticleQuery,
    ArticleCreateRequest,
    ArticleUpdateRequest,
)
from app.services.article.article_service import ArticleService

# 与用户模块头像共用同一套限制
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class AdminArticleService(ArticleService):
    """后台文章增删改。"""

    async def admin_list(self, query: AdminArticleQuery) -> dict:
        """后台列表：含草稿，不含已删。

        Returns:
            `{list, total, page, page_size}`。
        """
        page_size = min(query.page_size, 100)
        rows, total = await self._repo.paginate_admin(
            page=query.page,
            page_size=page_size,
            status=query.status,
            category_id=query.category_id,
            tag_id=query.tag_id,
            keyword=query.keyword,
        )
        items = await self._assemble(rows, None, with_updated_at=True)
        return {
            "list": items,
            "total": total,
            "page": query.page,
            "page_size": page_size,
        }

    async def create(self, req: ArticleCreateRequest, author_id: int) -> int:
        """新建文章。

        作者取当前登录的管理员，**不接受前端传 `user_id`** ——
        否则任何人都能冒充别人发文。

        Raises:
            BizError: 400 分类/标签不存在。
        """
        if not await self._repo.category_exists(req.type_id):
            raise BizError(ErrorCode.BAD_REQUEST, "分类不存在")

        await self._ensure_tags_exist(req.tag_ids)

        # 前端传的是完整 URL，入库要转成 object key；
        # 换域名/换 bucket 时只需改配置，不用全表 UPDATE
        cover_key = self._storage.parse_key(req.cover_url) if req.cover_url else ""

        article = Article(
            user_id=author_id,
            title=req.title,
            content=req.content,
            cover_url=cover_key,
            summary=req.summary or "",
            views=0,
            type_id=req.type_id,
            status=req.status,
        )
        article_id = await self._repo.create(article)

        await self._repo.replace_tags(article_id, req.tag_ids)
        await self._sync_images(article_id, req.content, is_update=False)

        await self._session.commit()
        logger.info("文章已创建 id={} title={}", article_id, req.title)
        return article_id

    async def update(self, article_id: int, req: ArticleUpdateRequest) -> None:
        """更新文章。只改传了的字段。

        正文变更会触发图片差集同步：删掉的图片从 MinIO 清理，新加的在
        `article_images` 里补记录。

        Raises:
            BizError: 404 不存在 / 400 分类标签不存在。
        """
        article = await self._repo.find_by_id(article_id)
        if article is None:
            raise BizError(ErrorCode.NOT_FOUND, "文章不存在")

        fields: dict[str, object] = {}
        if req.title is not None:
            fields["title"] = req.title
        if req.type_id is not None:
            if not await self._repo.category_exists(req.type_id):
                raise BizError(ErrorCode.BAD_REQUEST, "分类不存在")
            fields["type_id"] = req.type_id
        if req.summary is not None:
            fields["summary"] = req.summary
        if req.status is not None:
            fields["status"] = req.status
        if req.cover_url is not None:
            # 空字符串表示「去掉封面」
            fields["cover_url"] = self._storage.parse_key(req.cover_url) if req.cover_url else ""

        if fields:
            await self._repo.update_fields(article_id, **fields)

        if req.tag_ids is not None:
            await self._ensure_tags_exist(req.tag_ids)
            await self._repo.replace_tags(article_id, req.tag_ids)

        if req.content is not None:
            await self._repo.update_fields(article_id, content=req.content)
            await self._sync_images(article_id, req.content, is_update=True)

        await self._session.commit()
        logger.info("文章已更新 id={} fields={}", article_id, list(fields))

    async def delete(self, article_id: int) -> None:
        """删除文章（软删），并清理关联资源。

        顺序很重要：**先取图片 key，再删记录**。
        反过来的话，记录没了就不知道该去 MinIO 删哪些文件，图会变成孤儿，
        越积越多但没人敢清。

        Raises:
            BizError: 404 文章不存在。
        """
        row = await self._repo.find_by_id(article_id)
        if row is None:
            raise BizError(ErrorCode.NOT_FOUND, "文章不存在")
        article: Article = row[0]

        # 1. 先把要删的文件 key 收集齐
        image_keys = await self._repo.list_image_keys(article_id)
        cover_key = article.cover_url or ""

        # 2. 软删文章 + 软删评论 + 清关联 + 清图片记录
        await self._repo.soft_delete(article_id)
        await self._session.execute(
            update(Comment)
            .where(Comment.article_id == article_id, not_deleted(Comment))
            .values(deleted_at=func.now())
        )
        await self._repo.delete_tags_of(article_id)
        await self._repo.delete_images_of(article_id)
        await self._session.commit()

        # 3. 事务提交成功后再删文件。
        #    顺序反过来会出「文件删了、事务回滚了」的惨剧
        for key in [*image_keys, cover_key]:
            if key:
                # 失败只 warn：文章已经从库里删了，这里报错会让用户重试
                await self._storage.delete(key)

        logger.info(
            "文章已删除 id={} 清理图片 {} 张", article_id, len(image_keys) + (1 if cover_key else 0)
        )

    async def transfer_category(self, from_type_id: int, to_type_id: int) -> int:
        """批量转移分类。

        Raises:
            BizError: 400 分类不存在 / 源目标相同。
        """
        if from_type_id == to_type_id:
            raise BizError(ErrorCode.BAD_REQUEST, "源分类与目标分类相同")

        for category_id in (from_type_id, to_type_id):
            if not await self._repo.category_exists(category_id):
                raise BizError(ErrorCode.BAD_REQUEST, "分类不存在")

        count = await self._repo.transfer_category(from_type_id, to_type_id)
        await self._session.commit()
        logger.info("文章分类已转移 {} → {}，共 {} 篇", from_type_id, to_type_id, count)
        return count

    async def upload_image(self, file: UploadFile) -> str:
        """上传正文图片，返回完整 URL。

        Raises:
            BizError: 400 超限或格式不支持 / 500 上传失败。
        """
        ext = Path(file.filename or "").suffix.lower()
        if ext not in self._settings.business.allowed_image_exts:
            raise BizError(ErrorCode.BAD_REQUEST, "不支持的文件格式")

        data = await file.read()
        if len(data) > self._settings.business.image_max_bytes:
            raise BizError(ErrorCode.BAD_REQUEST, "图片大小不能超过 10MB")
        if not data:
            raise BizError(ErrorCode.BAD_REQUEST, "不支持的文件格式")

        today = datetime.now().strftime("%Y%m%d")
        object_name = f"all/{today}/{secrets.token_hex(8)}{ext}"
        await self._storage.upload(object_name, data, _EXT_TO_MIME[ext])
        return self._storage.public_url(object_name)

    # ============================================================
    # 内部
    # ============================================================

    async def _ensure_tags_exist(self, tag_ids: list[int]) -> None:
        """校验标签都存在。

        不做「自动创建不存在的标签」：那是另一个产品决策，
        悄悄建标签会让标签表越来越脏。

        Raises:
            BizError: 400 标签不存在。
        """
        if not tag_ids:
            return
        existing = await self._repo.tag_ids_exist(tag_ids)
        missing = set(tag_ids) - existing
        if missing:
            raise BizError(ErrorCode.BAD_REQUEST, f"标签不存在：{sorted(missing)}")

    async def _sync_images(self, article_id: int, content: str, *, is_update: bool) -> None:
        """同步文章引用到的图片。

        规则（照抄 Go 版的刻意行为）：

        - 正文新增的图 → 补记录
        - 正文删掉的图 → 删 MinIO 文件 + 删记录
        - **正文完全没有图时，不清空旧记录**。
          这是为了防止「误删正文全部内容又保存」时把图片一起干掉 ——
          用户可能只是清空重写，图还等着贴回去

        Args:
            article_id: 文章 ID。
            content: 正文。
            is_update: 是新建还是更新。
        """
        new_keys = self.extract_image_keys(content)
        old_keys = await self._repo.list_image_keys(article_id)

        if not new_keys and old_keys:
            # 空图不清空：保留旧记录，避免误删
            logger.debug("文章 id={} 正文无图，保留已有 {} 条图片记录", article_id, len(old_keys))
            return

        if is_update:
            removed = set(old_keys) - set(new_keys)
            for key in removed:
                await self._storage.delete(key)
            if removed:
                logger.info("文章 id={} 有 {} 张图被移除", article_id, len(removed))

        await self._repo.replace_images(article_id, new_keys)
