"""时间格式化。

看起来是小事，但 Go 版这里有**三种不一致的格式**，前端分别按各自格式解析，
重写时必须逐个复刻，不能统一：

| 位置                | 示例                            | 来源                                |
|---------------------|---------------------------------|-------------------------------------|
| 文章 created_at     | `2026-11-10T21:39:04Z`          | Go 的 `Format("2006-01-02T15:04:05Z")` |
| 评论 created_at     | `2026-11-10T21:39:04.123456+08:00` | Go 的 `time.Time` 直接 JSON 序列化  |
| 后台评论 created_at | `2026-11-10T21:39:04Z`          | 同文章                              |

统一成一种格式会让前端的某些 `new Date()` 解析出现时区偏移，这轮不动。
"""

from datetime import datetime


def format_time_z(dt: datetime | None) -> str:
    """按 Go 版文章接口的格式输出时间。

    ⚠️ 结尾的 `Z` 是**字面量，不代表 UTC**。数据库里存的是东八区本地时间，
    这里直接拼一个 `Z` 上去 —— 这是 Go 版的既有行为：

        article.CreatedAt.Format("2006-01-02T15:04:05Z")

    在 Go 的 layout 语法里，只有 `Z07:00` 才是时区标记，单独的 `Z` 就是普通字符。
    前端已按这个格式解析，改成真正的 UTC 需要同步改前端，本轮不做。

    Args:
        dt: 数据库读出的时间。None 时返回空串（接口里对应 `""` 而不是 `null`）。

    Returns:
        形如 `2026-11-10T21:39:04Z` 的字符串。
    """
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_time_iso(dt: datetime | None) -> str:
    """按 Go 版前台评论接口的格式输出时间。

    Go 那边评论的 `CreatedAt` 字段是 `time.Time` 类型，直接 JSON 序列化出来
    是带时区和微秒的 RFC3339：

        "created_at": "2026-11-10T21:39:04.123456+08:00"

    Python 的 `datetime.isoformat()` 生成同样的形状（带微秒与时区偏移），
    前提是时间对象带 tzinfo —— 从 `DATETIME` 列读出来的是 naive 对象，
    所以这里手工补上东八区。

    Args:
        dt: 数据库读出的时间（naive，东八区本地时间）。

    Returns:
        形如 `2026-11-10T21:39:04.123456+08:00` 的字符串。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        from datetime import timedelta, timezone

        # 数据库存的是东八区本地时间，读出来不带 tzinfo，补上再序列化
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    return dt.isoformat()
