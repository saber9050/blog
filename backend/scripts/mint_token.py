"""为本地调试 / 自动化测试签发 access token。

**为什么不直接调 `/auth/login`**：本项目的会话是「单设备」的 —— 会话存在
`refresh:{user_id}` 这一把 key 上，任何一次新登录都会覆盖它，正在使用的浏览器
下次刷新就会被判「Refresh Token 无效」并踢回登录页。自动化脚本为了拿个 token
去登录一次，等于把开发者自己顶下线。

这个脚本不碰登录接口：直接从 Redis 读出该用户当前有效的 `tid`，再用同样的
secret 现签一个 access token。会话不变，已登录的浏览器不受影响。

用法::

    python scripts/mint_token.py                       # 正常 token（管理员 id 44）
    python scripts/mint_token.py --user-id 12          # 指定用户
    python scripts/mint_token.py --expired             # 已过期的 token，测刷新用

输出一行 JSON：`{"token": "...", "user": {"id": ..., "name": ..., "roleId": ...}}`
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 脚本方式运行时 sys.path[0] 是 scripts/，import app 会失败
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import jwt  # noqa: E402
import redis  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    """签发并打印 token。"""
    parser = argparse.ArgumentParser(description="签发调试用 access token（不改动会话）")
    parser.add_argument("--user-id", type=int, default=44, help="用户 ID，默认 44（本地管理员）")
    parser.add_argument("--role-id", type=int, default=1, help="角色 ID，1=管理员")
    parser.add_argument("--username", default="dev", help="写进 token 的昵称快照")
    parser.add_argument("--expired", action="store_true", help="签发一个已过期的 token")
    parser.add_argument(
        "--tid",
        default=None,
        help="伪造一个会话 id（默认用 Redis 里的真实值）。用于验证「刷新时 tid 不匹配」的分支",
    )
    args = parser.parse_args()

    settings = get_settings()
    cache_conf = settings.database.redis
    client = redis.Redis(
        host=cache_conf.host,
        port=cache_conf.port,
        password=cache_conf.password or None,
        db=cache_conf.db,
    )

    if args.tid:
        tid = args.tid.encode()
    else:
        stored = client.get(f"refresh:{args.user_id}")
        if stored is None:
            print(
                f"用户 {args.user_id} 没有有效会话（refresh 键不存在）。"
                f"先正常登录一次再跑本脚本 —— 本脚本只复用会话，不创建会话。",
                file=sys.stderr,
            )
            return 1
        tid = stored

    now = int(time.time())
    expire = settings.jwt.access_expire_minutes * 60
    if args.expired:
        # 留 5 分钟余量，确保无论时钟偏差都被判定为过期
        payload = {"iat": now - expire - 600, "exp": now - 300}
    else:
        payload = {"iat": now, "exp": now + expire}

    token = jwt.encode(
        {
            "user_id": args.user_id,
            "username": args.username,
            "user_role_id": args.role_id,
            "tid": tid.decode(),
            **payload,
        },
        settings.jwt.secret.get_secret_value(),
        algorithm="HS256",
    )

    print(json.dumps({
        "token": token,
        "user": {"id": args.user_id, "name": args.username, "roleId": args.role_id},
        "expires_in": -1 if args.expired else expire,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
