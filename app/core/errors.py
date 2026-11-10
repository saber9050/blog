"""业务错误码与异常。

数值照抄 Go 版本的 `pkg/errors`，**一个都不能改**：
前端有按 `code` 分支的逻辑（比如 1004 提示「账号已禁用」、1006 触发刷新令牌），
改了等于线上功能失效。
"""

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。

    分四段：
      - 0       成功
      - 4xx/5xx 通用 HTTP 语义，与 HTTP 状态码一致
      - 1xxx    用户与认证相关
      - 2xxx    参数相关
      - 3xxx    资源相关
    """

    # ===== 成功 =====
    SUCCESS = 0

    # ===== 通用 =====
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    TOO_MANY_REQUESTS = 429
    INTERNAL_ERROR = 500
    NOT_IMPLEMENTED = 501
    SERVICE_UNAVAILABLE = 503

    # ===== 用户与认证 =====
    USER_NOT_FOUND = 1001
    USER_ALREADY_EXISTS = 1002
    INVALID_CREDENTIALS = 1003
    USER_DISABLED = 1004
    INVALID_TOKEN = 1005
    TOKEN_EXPIRED = 1006
    WRONG_PASSWORD = 1007
    TOKEN_NOT_EXPIRED = 1008
    LOGIN_LIMIT_REACHED = 1009

    # ===== 参数 =====
    INVALID_PARAM = 2001
    MISSING_PARAM = 2002
    PARAM_FORMAT_ERROR = 2003

    # ===== 资源 =====
    RESOURCE_NOT_FOUND = 3001
    RESOURCE_ALREADY_EXISTS = 3002
    RESOURCE_LOCKED = 3003


# 错误码的默认文案。业务代码通常自己给 message，
# 只在需要「用默认措辞」时才查这张表。
_CODE_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "成功",
    ErrorCode.BAD_REQUEST: "请求参数错误",
    ErrorCode.UNAUTHORIZED: "未授权",
    ErrorCode.FORBIDDEN: "禁止访问",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "方法不允许",
    ErrorCode.REQUEST_TIMEOUT: "请求超时",
    ErrorCode.CONFLICT: "资源冲突",
    ErrorCode.TOO_MANY_REQUESTS: "请求过于频繁",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.NOT_IMPLEMENTED: "功能未实现",
    ErrorCode.SERVICE_UNAVAILABLE: "服务不可用",
    ErrorCode.USER_NOT_FOUND: "用户不存在",
    ErrorCode.USER_ALREADY_EXISTS: "用户已存在",
    ErrorCode.INVALID_CREDENTIALS: "用户名或密码错误",
    ErrorCode.USER_DISABLED: "用户已被禁用",
    ErrorCode.INVALID_TOKEN: "无效的令牌",
    ErrorCode.TOKEN_EXPIRED: "令牌已过期",
    ErrorCode.WRONG_PASSWORD: "密码错误",
    ErrorCode.TOKEN_NOT_EXPIRED: "令牌尚未过期",
    ErrorCode.LOGIN_LIMIT_REACHED: "当前登录人数已达上限，请重新登录",
    ErrorCode.INVALID_PARAM: "参数错误",
    ErrorCode.MISSING_PARAM: "缺少必要参数",
    ErrorCode.PARAM_FORMAT_ERROR: "参数格式错误",
    ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorCode.RESOURCE_ALREADY_EXISTS: "资源已存在",
    ErrorCode.RESOURCE_LOCKED: "资源已被锁定",
}


def message_of(code: int) -> str:
    """取错误码的默认文案。未知码返回「未知错误」。"""
    return _CODE_MESSAGES.get(code, "未知错误")


class BizError(Exception):
    """业务异常。

    为什么用异常而不是 Go 那样的 `(result, error)` 双返回值：
    Python 没有多返回值，异常是唯一能让调用链自然中断、又不用每层写
    `if err != nil { return }` 的机制。

    使用约定：
      - **service 层抛它**，controller 与 repository 不抛业务异常
      - 全局异常处理器捕获后转成统一响应，绝不让堆栈泄露给前端
    """

    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        """构造业务异常。

        Args:
            code: 业务错误码。
            message: 面向用户的提示。不传则用错误码的默认文案。
        """
        self.code = code
        self.message = message if message is not None else message_of(code)
        super().__init__(self.message)

    @property
    def http_status(self) -> int:
        """业务码映射到 HTTP 状态码。

        规则与 Go 版一致：
          - 4xx / 5xx：直接用码值
          - 1xxx - 3xxx：统一 400（前端只认 body 里的 code）

        这样做的原因：1004「用户已禁用」既不是 401 也不是 403 的标准语义，
        与其拍脑袋映射成某个 4xx，不如统一 400 让前端按 code 判断。
        """
        code = int(self.code)
        if 400 <= code < 600:
            return code
        return 400

    def __repr__(self) -> str:
        return f"BizError(code={int(self.code)}, message={self.message!r})"
