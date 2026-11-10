"""大模型配置表。

配置存库而不是写配置文件，原因：
- 换模型不用重启服务
- api_key 不进 Git
- 后台可以「测试连接」，填错了当场发现

与 Go 版的差异：
- **不建 `dimension` 列**（那是 embedding 模型的向量维度，向量功能已删除）
- **不建 `name` 列**（Go 侧注释自己写了「仅为满足历史 not null 约束」）
- `type` 列保留，恒为 1（对话模型）。前端列表可能按它判断类型，保留不用改前端。
"""

from sqlalchemy import Double, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# 模型类型常量。新库只会出现 CHAT，保留 EMBEDDING 常量是为了
# 兼容「从旧库手工导入的数据」这种边角场景。
MODEL_TYPE_CHAT = 1
MODEL_TYPE_EMBEDDING = 2


class AIModelConfig(Base, TimestampMixin):
    """OpenAI 兼容协议的对话模型配置。

    `api_key` 存的是 **Fernet 密文**，不是明文。
    读取时经 `CryptoBox.decrypt()` 还原；接口响应只返回脱敏后的前后缀。
    """

    __tablename__ = "ai_model_configs"

    base_url: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="API 基址，到 /v1 为止"
    )
    api_key: Mapped[str] = mapped_column(Text, nullable=False, comment="Fernet 密文，绝不返回明文")
    model: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="模型 ID，如 deepseek-chat"
    )
    type: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default="1",
        comment="类型：1 对话模型 / 2 向量模型（新库恒为 1）",
    )
    timeout_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30", comment="单次调用超时秒数"
    )
    max_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="2048", comment="单次生成 token 上限"
    )
    temperature: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0.3", comment="采样温度"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1", comment="状态：1 启用 / 0 禁用"
    )

    def __repr__(self) -> str:
        """调试用表示。**不输出 api_key**，哪怕是密文。"""
        return f"<AIModelConfig id={self.id} model={self.model!r} status={self.status}>"
