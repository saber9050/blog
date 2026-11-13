"""日志配置。

用 loguru 而不是标准库 logging：
- 自带彩色控制台输出，开发时不用配 formatter
- 文件轮转 / 保留 / 压缩一行配置搞定，对应 Go 版 zap 的
  `max_size` / `max_backups` / `max_age` / `compress`
- 异常自动带完整堆栈，不用手写 `logger.exception`

约定：业务代码统一 `from loguru import logger`，不要再包一层自己的日志类 ——
那层封装最后只会多一个「取 logger 要 import 哪个」的困惑。
"""

import sys
from pathlib import Path

from loguru import logger

from app.core.config import BACKEND_ROOT, Settings

# 控制台格式：时间 | 级别 | 模块:行号 | 消息
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# 文件格式：带进程号，方便多 worker 时区分来源
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{process} | {name}:{function}:{line} - {message}"
)


class LoggingConfigurator:
    """日志初始化。

    只在应用启动时调用一次；重复调用会重复添加 handler，
    所以内部先 `logger.remove()` 清掉默认输出。
    """

    @staticmethod
    def setup(settings: Settings) -> None:
        """配置日志。

        Args:
            settings: 全局配置，取 `log_level` / `log_dir` /
                `log_rotation` / `log_retention` 四个字段。
        """
        logger.remove()

        # ---- 控制台 ----
        # debug 模式打 DEBUG，release 只打 INFO 以上
        console_level = "DEBUG" if settings.is_debug else settings.log.level.upper()
        logger.add(
            sys.stderr,
            level=console_level,
            format=_CONSOLE_FORMAT,
            colorize=True,
            # 只输出业务 message，不打印 loguru 自己的调试信息
            backtrace=False,
            diagnose=False,
        )

        # ---- 文件 ----
        # 相对路径一律按 backend/ 解析，不跟着「当前工作目录」走。
        # 否则从项目根启动日志会落在 blog/logs/，从 backend/ 启动落在 backend/logs/，
        # 排查问题时翻错文件。想换位置就在配置里写绝对路径。
        log_dir = Path(settings.log.dir)
        if not log_dir.is_absolute():
            log_dir = BACKEND_ROOT / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=settings.log.level.upper(),
            format=_FILE_FORMAT,
            rotation=settings.log.rotation,  # 例如 "50 MB"
            retention=settings.log.retention,  # 例如 "7 days"
            compression="zip",
            encoding="utf-8",
            # 生产环境不打变量值（可能含密码），只留堆栈
            diagnose=settings.is_debug,
            backtrace=settings.is_debug,
            enqueue=True,  # 异步写入，避免磁盘慢时阻塞事件循环
        )

        logger.info(
            "日志系统已就绪 | level={} | dir={} | mode={}",
            settings.log.level,
            log_dir.resolve(),
            settings.app.mode,
        )


def log_startup_banner(settings: Settings) -> None:
    """打印启动横幅。

    与 Go 版保持同样的信息量：应用名、版本、模式、监听地址。
    配置里出现的密钥字段一律不打印。
    """
    logger.info("=" * 56)
    logger.info(" {} 启动中", settings.app.name)
    logger.info(" 模式    : {}", settings.app.mode)
    logger.info(" 监听    : {}:{}", settings.app.host, settings.app.port)
    logger.info(
        " 数据库  : {}:{}/{}",
        settings.database.mysql.host,
        settings.database.mysql.port,
        settings.database.mysql.database,
    )
    logger.info(" Redis   : {}", "启用" if settings.database.redis.enabled else "未启用")
    logger.info(" MinIO   : {} (bucket={})", settings.minio.endpoint, settings.minio.bucket)
    logger.info("=" * 56)
