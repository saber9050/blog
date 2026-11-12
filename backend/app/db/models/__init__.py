"""ORM 模型汇总。

Alembic 的 `env.py` 与建表脚本都从这里取模型清单，
避免「新增了模型但忘记注册，迁移里少了张表」这种问题。

对应 Go 版的 `entity.AllModels()`：启动、迁移工具、集成测试三处共用一份清单。
"""

from app.db.models.about import About
from app.db.models.article import Article, ArticleImage
from app.db.models.comment import Comment
from app.db.models.like import Like
from app.db.models.llm_config import MODEL_TYPE_CHAT, MODEL_TYPE_EMBEDDING, AIModelConfig
from app.db.models.taxonomy import Category, Tag, TagArticle
from app.db.models.user import User

__all__ = [
    "AIModelConfig",
    "MODEL_TYPE_CHAT",
    "MODEL_TYPE_EMBEDDING",
    "About",
    "Article",
    "ArticleImage",
    "Category",
    "Comment",
    "Like",
    "Tag",
    "TagArticle",
    "User",
    "ALL_MODELS",
]

#: 需要建表的全部模型，顺序即建表顺序（被引用的表在前）。
#: 注意：本项目的表之间**没有物理外键**，所以顺序不是硬性要求，
#: 保持「业务上被依赖的在前」只是为了阅读方便。
ALL_MODELS: tuple[type, ...] = (
    User,
    Category,
    Tag,
    Article,
    TagArticle,
    ArticleImage,
    Comment,
    Like,
    About,
    AIModelConfig,
)
