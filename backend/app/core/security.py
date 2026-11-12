"""安全相关：密码哈希、JWT 签发解析、对称加解密。

三个类各管一件事，互相不依赖：

    PasswordHasher  密码 → bcrypt 哈希
    JWTManager      双 Token 的签发与解析
    CryptoBox       第三方密钥的落库加密（模型 api_key）
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import BizError, ErrorCode

# ============================================================
# 密码哈希
# ============================================================


class PasswordHasher:
    """bcrypt 密码哈希。

    为什么直接用 `bcrypt` 原生库而不是 passlib：
    passlib 1.7.4 会读 `bcrypt.__about__.__version__`，而 bcrypt 4.x 删了这个属性，
    结果是每次调用都打一条 AttributeError 警告，且未来会直接不可用。
    bcrypt 原生 API 只有 hash/checkpw 两个函数，没有封装的必要。
    """

    # cost=12 是 2024 年之后的推荐值（10 在 2026 年偏弱）。
    # 每 +1 计算量翻倍，12 在普通机器上约 0.2 秒，登录体验可接受。
    DEFAULT_ROUNDS = 12

    # bcrypt 算法本身只取前 72 字节，超出部分被静默丢弃。
    # 不主动拦截的话，「72 字节正确 + 后面随便」也能登录成功。
    MAX_PASSWORD_BYTES = 72

    def __init__(self, rounds: int = DEFAULT_ROUNDS) -> None:
        """初始化。

        Args:
            rounds: bcrypt 的 cost 参数，越大越慢越安全。
        """
        self._rounds = rounds

    def hash(self, plain: str) -> str:
        """生成密码哈希。

        Args:
            plain: 明文密码。

        Returns:
            形如 `$2b$12$...` 的 60 字符哈希串。

        Raises:
            ValueError: 密码超过 bcrypt 的 72 字节上限。
        """
        raw = plain.encode("utf-8")
        if len(raw) > self.MAX_PASSWORD_BYTES:
            raise ValueError(f"密码长度不能超过 {self.MAX_PASSWORD_BYTES} 字节")
        # gensalt(rounds) 返回的盐里已经带了 cost 参数，哈希串会保存它，
        # 所以校验时不需要再传 rounds
        return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=self._rounds)).decode("utf-8")

    def verify(self, plain: str, hashed: str) -> bool:
        """校验密码。

        Args:
            plain: 用户输入的明文。
            hashed: 库里的哈希串。

        Returns:
            是否匹配。哈希串格式非法时返回 False 而不是抛异常 ——
            脏数据不该让登录接口 500。
        """
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, TypeError):
            return False


# ============================================================
# JWT
# ============================================================


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """access token 里携带的信息。

    字段名与 Go 版的 `CustomClaims` 一一对应，`sub` 不放用户 ID
    （Go 版用的是 `user_id`，保持原样，避免两边解析逻辑不一致）。
    """

    user_id: int
    username: str
    role_id: int
    tid: str
    # 过期时间戳（秒）。刷新接口允许读过期 token，所以这里仍保留原值
    exp: int


class JWTManager:
    """双 Token 的签发与解析。

    机制说明（照抄 Go 版）：

    - **access token** 是 JWT，15 分钟过期，放在 `Authorization: Bearer` 头里
    - **refresh token** 不是 JWT，是 32 字节随机 hex，存在 Redis 的 `refresh:{user_id}`
    - access token 的 payload 里带一个 `tid` 字段，值就等于当前 refresh token
    - 刷新时：用允许过期的模式解析 access → 取出 `tid` → 与 Redis 比对
      → 一致则签发新的 access + 新的 refresh（轮换），并覆盖 Redis

    这样做的收益：refresh token 从不下发给前端，XSS 偷不到长期凭证。
    代价：单设备登录（新登录覆盖旧会话）。
    """

    ALGORITHM = "HS256"

    def __init__(self, secret: str, access_expire_minutes: int = 15) -> None:
        """初始化。

        Args:
            secret: HS256 签名密钥。
            access_expire_minutes: access token 有效期（分钟）。
        """
        self._secret = secret
        self._access_expire = timedelta(minutes=access_expire_minutes)

    def create_access_token(self, user_id: int, username: str, role_id: int, tid: str) -> str:
        """签发 access token。

        Args:
            user_id: 用户 ID。
            username: 昵称快照（token 有效期内改名不影响已签发的 token）。
            role_id: 角色 ID，1=管理员。
            tid: 当前会话的 refresh token 值，用于刷新时校验。

        Returns:
            JWT 字符串。
        """
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "user_id": user_id,
            "username": username,
            "user_role_id": role_id,
            "tid": tid,
            "iat": int(now.timestamp()),
            "exp": int((now + self._access_expire).timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def create_purpose_token(self, claims: dict[str, Any], expire_seconds: int) -> str:
        """签发一次性用途的 token（目前用于「换绑邮箱」的确认链接）。

        这类 token 不进 Redis，靠「用一次就拉黑」保证不可重放。

        Args:
            claims: 自定义负载，例如 `{"user_id": 1, "email": "new@qq.com"}`。
            expire_seconds: 有效期（秒）。

        Returns:
            JWT 字符串。
        """
        now = datetime.now(UTC)
        payload = {
            **claims,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expire_seconds)).timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def decode(self, token: str, *, verify_exp: bool = True) -> TokenClaims:
        """解析 access token。

        Args:
            token: 去掉 `Bearer ` 前缀后的字符串。
            verify_exp: 是否校验过期。**刷新接口必须传 False**，
                否则 access token 一过期就永远刷不了新 token，
                双 Token 机制直接失效。

        Returns:
            解析后的 claims。

        Raises:
            BizError: 1006 令牌过期 / 1005 令牌无效。
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": verify_exp},
            )
        except jwt.ExpiredSignatureError as exc:
            raise BizError(ErrorCode.TOKEN_EXPIRED, "令牌已过期") from exc
        except jwt.InvalidTokenError as exc:
            raise BizError(ErrorCode.INVALID_TOKEN, "无效的令牌") from exc

        # 缺字段视为无效 token：宁可让用户重登，也不要拿半截 claims 去查库
        try:
            return TokenClaims(
                user_id=int(payload["user_id"]),
                username=str(payload["username"]),
                role_id=int(payload["user_role_id"]),
                tid=str(payload["tid"]),
                exp=int(payload["exp"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BizError(ErrorCode.INVALID_TOKEN, "无效的令牌") from exc

    def decode_raw(self, token: str, *, verify_exp: bool = True) -> dict[str, Any]:
        """解析任意负载的 token（用途 token 用）。

        Returns:
            原始 payload 字典。

        Raises:
            BizError: 令牌过期 / 无效。
        """
        try:
            return jwt.decode(
                token,
                self._secret,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": verify_exp},
            )
        except jwt.ExpiredSignatureError as exc:
            raise BizError(ErrorCode.TOKEN_EXPIRED, "令牌已过期") from exc
        except jwt.InvalidTokenError as exc:
            raise BizError(ErrorCode.INVALID_TOKEN, "无效的令牌") from exc

    @staticmethod
    def generate_refresh_token() -> str:
        """生成 refresh token。

        Returns:
            64 个字符的随机 hex（32 字节熵）。同时充当会话标识 `tid`。
        """
        return secrets.token_hex(32)


# ============================================================
# 对称加密
# ============================================================


class CryptoBox:
    """对称加解密，用于保管第三方密钥（目前只有模型的 `api_key`）。

    用 `cryptography` 的 Fernet（AES-128-CBC + HMAC-SHA256）：
    自带完整性校验，密文被篡改会抛 `InvalidToken`，不会解出一堆乱码。

    密钥为空时进入**明文透传模式**：本地开发不必先生成 key 就能跑。
    生产环境必须在 `.env` 里配置 `FERNET_KEY`，否则 `is_secure` 为 False，
    启动日志会打警告。
    """

    def __init__(self, key: str) -> None:
        """初始化。

        Args:
            key: Fernet key（32 字节的 base64 串）。空字符串表示明文透传。
        """
        self._fernet: Fernet | None = None
        if key:
            try:
                self._fernet = Fernet(key.encode("utf-8"))
            except (ValueError, TypeError):
                # key 格式错误不直接崩进程：先降级为明文，启动日志里会警告，
                # 让开发者先去修配置，而不是对着一个起不来的服务发懵
                self._fernet = None

    @property
    def is_secure(self) -> bool:
        """是否处于加密模式。"""
        return self._fernet is not None

    def encrypt(self, plain: str) -> str:
        """加密。

        Args:
            plain: 明文。

        Returns:
            base64 文本，可直接存 VARCHAR 列；明文模式下原样返回。
        """
        if self._fernet is None or not plain:
            return plain
        return self._fernet.encrypt(plain.encode("utf-8")).decode("utf-8")

    def decrypt(self, cipher: str) -> str:
        """解密。

        Args:
            cipher: 密文；明文模式下原样返回。

        Raises:
            BizError: 500 密文损坏或密钥换过。调用方应提示
                「请重新填写模型密钥」，而不是把异常堆栈抛给前端。
        """
        if self._fernet is None or not cipher:
            return cipher
        try:
            return self._fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise BizError(
                ErrorCode.INTERNAL_ERROR,
                "模型密钥解密失败，请到「AI 模型」页重新填写 api_key",
            ) from exc
