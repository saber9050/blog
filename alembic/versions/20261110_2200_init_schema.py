"""初始化 10 张业务表

Revision ID: 20261110_2200_init_schema
Revises:
Create Date: 2026-11-10 22:00:00

与 Go 版 PostgreSQL 结构的差异（均为有意为之）：

1. 去掉 4 个向量化列：`articles.vector_status` /
   `vector_chunk_count` / `vector_error` / `vectorized_at`
2. 去掉 `ai_model_configs.dimension` / `name`
3. 新增 3 个唯一约束：`likes(article_id, user_id)`、
   `categorys.category_name`、`tags.tag_name`
4. `articles.content` 用 `MEDIUMTEXT`（16 MB），不用 `TEXT`（64 KB 会被静默截断）
5. 表名 `categorys` 保留原拼写

所有表**不建物理外键**：与 Go 版一致，一致性由应用层保证。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

# Alembic 的版本标识
revision: str = "20261110_2200_init_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    """三张表共用的主键与时间戳列。

    Returns:
        列定义列表，可直接展开进 `op.create_table()`。
    """
    return [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="更新时间",
        ),
    ]


def upgrade() -> None:
    """建表。

    顺序按「被依赖的在前」排列，便于阅读；因为没有物理外键，
    实际顺序不影响执行。
    """

    # ---------------- users ----------------
    op.create_table(
        "users",
        *_timestamps(),
        sa.Column("user_name", sa.String(50), nullable=False, comment="昵称"),
        sa.Column("account", sa.String(50), nullable=False, comment="账号"),
        sa.Column("password_hash", sa.String(255), nullable=False, comment="bcrypt 密码哈希"),
        sa.Column("email", sa.String(50), nullable=True, comment="邮箱"),
        sa.Column("introduction", sa.Text(), nullable=True, comment="个人简介"),
        sa.Column("avatar_url", sa.String(255), nullable=True, comment="头像 object key"),
        sa.Column(
            "status",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
            comment="1 启用 / 0 禁用",
        ),
        sa.Column(
            "role_id",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
            comment="1 管理员 / 0 普通",
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("user_name", name="uq_users_user_name"),
        sa.UniqueConstraint("account", name="uq_users_account"),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    # ---------------- categorys ----------------
    op.create_table(
        "categorys",
        *_timestamps(),
        sa.Column("category_name", sa.String(50), nullable=False, comment="分类名"),
        sa.Column(
            "status",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
            comment="1 启用 / 0 禁用",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categorys"),
        sa.UniqueConstraint("category_name", name="uq_categorys_category_name"),
    )

    # ---------------- tags ----------------
    op.create_table(
        "tags",
        *_timestamps(),
        sa.Column("tag_name", sa.String(100), nullable=False, comment="标签名"),
        sa.Column(
            "status",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
            comment="1 启用 / 0 禁用",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("tag_name", name="uq_tags_tag_name"),
    )

    # ---------------- articles ----------------
    op.create_table(
        "articles",
        *_timestamps(),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="作者 ID"),
        sa.Column("title", sa.String(100), nullable=False, comment="标题"),
        # 关键：MEDIUMTEXT，不是 TEXT。TEXT 上限 64 KB 且超限静默截断
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False, comment="Markdown 正文"),
        sa.Column("cover_url", sa.String(255), nullable=True, comment="封面 object key"),
        sa.Column("summary", sa.String(255), nullable=True, comment="摘要"),
        sa.Column("views", sa.BigInteger(), server_default="0", nullable=False, comment="浏览量"),
        sa.Column("type_id", sa.BigInteger(), nullable=False, comment="分类 ID"),
        sa.Column(
            "status",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
            comment="1 发布 / 0 草稿",
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name="pk_articles"),
        comment="文章",
    )
    op.create_index("ix_articles_deleted_at", "articles", ["deleted_at"])
    op.create_index("ix_articles_type_id_status", "articles", ["type_id", "status"])
    op.create_index("ix_articles_status_created_at", "articles", ["status", "created_at"])

    # ---------------- tag_articles ----------------
    op.create_table(
        "tag_articles",
        *_timestamps(),
        sa.Column("article_id", sa.BigInteger(), nullable=False, comment="文章 ID"),
        sa.Column("tag_id", sa.BigInteger(), nullable=False, comment="标签 ID"),
        sa.PrimaryKeyConstraint("id", name="pk_tag_articles"),
    )
    op.create_index("ix_tag_articles_article_id", "tag_articles", ["article_id"])
    op.create_index("ix_tag_articles_tag_id", "tag_articles", ["tag_id"])

    # ---------------- article_images ----------------
    op.create_table(
        "article_images",
        *_timestamps(),
        sa.Column("article_id", sa.BigInteger(), nullable=False, comment="文章 ID"),
        sa.Column("url", sa.String(255), nullable=True, comment="图片 object key"),
        sa.PrimaryKeyConstraint("id", name="pk_article_images"),
    )
    op.create_index("ix_article_images_article_id", "article_images", ["article_id"])

    # ---------------- comments ----------------
    op.create_table(
        "comments",
        *_timestamps(),
        sa.Column("article_id", sa.BigInteger(), nullable=False, comment="所属文章 ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="评论者 ID"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True, comment="父评论 ID，NULL 为一级"),
        sa.Column("content", sa.Text(), nullable=False, comment="评论内容"),
        sa.Column(
            "reply_to_name",
            sa.String(100),
            server_default="",
            nullable=True,
            comment="回复目标昵称快照",
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
    )
    op.create_index("ix_comments_deleted_at", "comments", ["deleted_at"])
    op.create_index("ix_comments_article_id_parent_id", "comments", ["article_id", "parent_id"])
    op.create_index("ix_comments_user_id", "comments", ["user_id"])

    # ---------------- likes ----------------
    op.create_table(
        "likes",
        *_timestamps(),
        sa.Column("article_id", sa.BigInteger(), nullable=False, comment="文章 ID"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="用户 ID"),
        sa.PrimaryKeyConstraint("id", name="pk_likes"),
        # 本轮新增：杜绝并发重复点赞
        sa.UniqueConstraint("article_id", "user_id", name="uq_likes_article_id_user_id"),
    )

    # ---------------- abouts ----------------
    op.create_table(
        "abouts",
        *_timestamps(),
        sa.Column("tech_stack", sa.String(255), nullable=True, comment="技术栈，逗号分隔"),
        sa.Column("my_story", sa.Text(), nullable=True, comment="我的故事"),
        sa.Column("why", sa.Text(), nullable=True, comment="为什么建站"),
        sa.Column("interest", sa.String(255), nullable=True, comment="感兴趣的方向，逗号分隔"),
        sa.Column("git_hub", sa.String(255), nullable=True, comment="GitHub 地址"),
        sa.Column("csdn", sa.String(255), nullable=True, comment="CSDN 地址"),
        sa.PrimaryKeyConstraint("id", name="pk_abouts"),
    )

    # ---------------- ai_model_configs ----------------
    op.create_table(
        "ai_model_configs",
        *_timestamps(),
        sa.Column("base_url", sa.String(255), nullable=False, comment="API 基址，到 /v1"),
        # Fernet 密文比明文长，Text 更稳妥
        sa.Column("api_key", sa.Text(), nullable=False, comment="Fernet 密文"),
        sa.Column("model", sa.String(128), nullable=False, comment="模型 ID"),
        sa.Column(
            "type",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
            comment="1 对话模型 / 2 向量模型（新库恒为 1）",
        ),
        sa.Column(
            "timeout_sec", sa.Integer(), server_default="30", nullable=False, comment="超时秒"
        ),
        sa.Column(
            "max_tokens", sa.Integer(), server_default="2048", nullable=False, comment="生成上限"
        ),
        sa.Column(
            "temperature", sa.Double(), server_default="0.3", nullable=False, comment="采样温度"
        ),
        sa.Column(
            "status",
            sa.SmallInteger(),
            server_default="1",
            nullable=False,
            comment="1 启用 / 0 禁用",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_model_configs"),
    )


def downgrade() -> None:
    """删除全部表。

    顺序与建表相反。MySQL 的 DDL 不支持事务，执行中途失败会留下半成品，
    重建时先手工确认库是否干净。
    """
    op.drop_table("ai_model_configs")
    op.drop_table("abouts")
    op.drop_table("likes")
    op.drop_index("ix_comments_user_id", table_name="comments")
    op.drop_index("ix_comments_article_id_parent_id", table_name="comments")
    op.drop_index("ix_comments_deleted_at", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_article_images_article_id", table_name="article_images")
    op.drop_table("article_images")
    op.drop_index("ix_tag_articles_tag_id", table_name="tag_articles")
    op.drop_index("ix_tag_articles_article_id", table_name="tag_articles")
    op.drop_table("tag_articles")
    op.drop_index("ix_articles_status_created_at", table_name="articles")
    op.drop_index("ix_articles_type_id_status", table_name="articles")
    op.drop_index("ix_articles_deleted_at", table_name="articles")
    op.drop_table("articles")
    op.drop_table("tags")
    op.drop_table("categorys")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_table("users")
