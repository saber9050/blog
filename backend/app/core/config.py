"""全局配置。

配置来源（优先级从高到低）：

    1. 环境变量        APP__PORT=8000           ← 只用于 Docker / CI 注入密钥
    2. configs/config.yaml                       ← 唯一的主配置源
    3. 本文件里的默认值                          ← 保证缺项也能跑

为什么只用一份 YAML、不保留 `.env`：

Go 版本同时维护 `config.yaml` 和 `.env`，README 里专门写过
「两边密码必须一致，否则连不上库」。那不是一个配置系统，是两个配置系统
靠人肉同步。这里只留 YAML：本地改它就够，容器里用环境变量覆盖个别敏感项。

嵌套结构的来源：配置项已经 30 多个，扁平 key-value 读起来太累。
YAML 按 `app` / `database` / `jwt` / `minio` 分组，与 Go 版的 `config.yaml` 一致。
"""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, SecretStr, computed_field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# backend/ 根目录：本文件在 app/core/config.py，往上三层
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent

# 配置文件路径。
#
# **必须基于 __file__ 算绝对路径，不能用相对路径**。相对路径跟着「当前工作目录」
# 走，而工作目录取决于谁启动的进程：
#   - PyCharm 默认把工作目录设成项目根（blog/），于是 configs/config.yaml 找不到
#   - 命令行在 backend/ 下启动才碰巧能对上
# 找不到时 pydantic-settings 不报错，直接回退到本文件的默认值 ——
# 症状是「我明明配了 debug，怎么起来是 release」「MinIO 地址怎么变成 127.0.0.1 了」。
#
# 容器里用 CONFIG_FILE 环境变量指到挂载点，优先级最高。
CONFIG_FILE = Path(
    os.getenv("CONFIG_FILE", str(BACKEND_ROOT / "configs" / "config.yaml"))
).resolve()

if not CONFIG_FILE.is_file():
    # 这里只能 print：日志系统由 LoggingConfigurator 初始化，而它依赖本对象，
    # 此刻还没配置好。用 stderr 保证不会被 stdout 的缓冲吞掉。
    print(
        f"[config] 配置文件不存在：{CONFIG_FILE}\n"
        f"[config] 将使用代码内置默认值（mode=release / 本地地址），"
        f"配置里的库密码、MinIO 地址都不会生效。",
        file=sys.stderr,
    )


# ============================================================
# 分组配置
# ============================================================


class AppSection(BaseModel):
    """应用基础信息。"""

    name: str = "blog-project"
    mode: Literal["debug", "release"] = "release"
    host: str = "127.0.0.1"
    port: int = 8000
    # 对外可访问的站点根地址，用于拼邮件里的确认链接。
    # service 层拿不到 request，只能靠配置；部署时改成真实域名。
    site_url: str = "http://127.0.0.1:8000"


class MySQLSection(BaseModel):
    """MySQL 连接参数。"""

    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: SecretStr = SecretStr("")
    database: str = "blog_v2"
    pool_size: int = 10
    max_overflow: int = 20
    # 打印每条 SQL，排查 N+1 时打开
    echo: bool = False


class RedisSection(BaseModel):
    """Redis 连接参数。

    `enabled=false` 时降级为进程内缓存，本地开发不必先起 Redis。
    ⚠️ 多 worker 部署时必须开，否则验证码会「这台发的、那台验不过」。
    """

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 6379
    password: SecretStr = SecretStr("")
    db: int = 0


class DatabaseSection(BaseModel):
    """数据库总配置。"""

    mysql: MySQLSection = Field(default_factory=MySQLSection)
    redis: RedisSection = Field(default_factory=RedisSection)


class JWTSection(BaseModel):
    """双 Token 参数。"""

    secret: SecretStr = SecretStr("change-me")
    access_expire_minutes: int = 15
    refresh_expire_hours: int = 72


class SecuritySection(BaseModel):
    """加密相关。

    `fernet_key` 用于模型 api_key 的落库加密。
    留空则以明文存储（仅限本地调试），启动时会打警告。
    """

    fernet_key: SecretStr = SecretStr("")


class MinioSection(BaseModel):
    """对象存储参数。"""

    endpoint: str = "127.0.0.1:9000"
    access_key: str = ""
    secret_key: SecretStr = SecretStr("")
    bucket: str = "blog-v2"
    use_ssl: bool = False
    # 浏览器访问地址，必须是纯源（不要带路径前缀，否则封面 403）
    public_url: str = "http://127.0.0.1:9000"


class SmtpSection(BaseModel):
    """邮件发送参数（QQ 邮箱 587 端口 STARTTLS）。"""

    host: str = "smtp.qq.com"
    port: int = 587
    username: str = ""
    password: SecretStr = SecretStr("")


class AdminSection(BaseModel):
    """默认管理员。首次启动且库里没有管理员时自动创建。"""

    enabled: bool = True
    account: str = "00000000000"
    password: SecretStr = SecretStr("admin123456")


class LogSection(BaseModel):
    """日志参数。对应 Go 版 zap 的 max_size / max_backups / max_age。"""

    level: str = "INFO"
    dir: str = "logs"
    rotation: str = "50 MB"
    retention: str = "7 days"


class BusinessSection(BaseModel):
    """业务常量。

    集中放这里而不是散落在代码里，改阈值不用翻全项目。
    """

    # 图片上传
    image_max_bytes: int = 10 * 1024 * 1024
    allowed_image_exts: list[str] = Field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".webp"]
    )
    # 验证码
    captcha_length: int = 6
    captcha_expire_seconds: int = 300
    captcha_send_limit_seconds: int = 60
    # 分页
    max_page_size: int = 100


# ============================================================
# 根配置
# ============================================================


class Settings(BaseSettings):
    """应用配置根对象。

    字段名与 `config.yaml` 的顶层键一一对应：

        app:        → settings.app
        database:   → settings.database
        jwt:        → settings.jwt
        ...
    """

    model_config = SettingsConfigDict(
        yaml_file=str(CONFIG_FILE),
        yaml_file_encoding="utf-8",
        # 环境变量用双下划线表示层级：DATABASE__MYSQL__PASSWORD
        env_nested_delimiter="__",
        # 允许 YAML 里出现本类没声明的键（比如未来的扩展段），不报错
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSection = Field(default_factory=AppSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    jwt: JWTSection = Field(default_factory=JWTSection)
    security: SecuritySection = Field(default_factory=SecuritySection)
    minio: MinioSection = Field(default_factory=MinioSection)
    smtp: SmtpSection = Field(default_factory=SmtpSection)
    admin: AdminSection = Field(default_factory=AdminSection)
    log: LogSection = Field(default_factory=LogSection)
    business: BusinessSection = Field(default_factory=BusinessSection)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """定义配置来源与优先级。

        **必须显式写这个方法**：pydantic-settings 默认只认环境变量、
        `.env` 和 secrets 目录，YAML 不在默认链路里。只声明 `yaml_file`
        不会生效 —— 而且它不会报错，只会静默用默认值，
        典型症状就是「我改了 config.yaml 但程序没反应」。

        优先级（前面的覆盖后面的）：

            1. init_settings     显式传参，测试用（Settings(app=...)）
            2. env_settings      环境变量，容器部署注入密钥
            3. YAML 文件          主配置源
            4. file_secret        /run/secrets 之类，暂未使用

        Returns:
            按优先级排列的来源元组。
        """
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """拼 SQLAlchemy 的 MySQL 连接串。

        密码必须做 URL 编码：`p@ss/w0rd` 里的 `@` 和 `/` 会被当成主机分隔符，
        导致连接串被截断 —— 这是最常见的「本地能连、部署连不上」原因。
        """
        m = self.database.mysql
        pwd = quote_plus(m.password.get_secret_value())
        return f"mysql+asyncmy://{m.user}:{pwd}@{m.host}:{m.port}/{m.database}?charset=utf8mb4"

    @property
    def is_debug(self) -> bool:
        """是否调试模式。决定接口文档是否开放、SQL 是否回显。"""
        return self.app.mode == "debug"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例。

    用 `lru_cache` 而不是模块级全局变量：
    测试里可以 `get_settings.cache_clear()` 重新加载，不污染进程状态。
    """
    return Settings()
