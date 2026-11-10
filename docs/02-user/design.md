# 02 用户模块 · 设计方案

## 1. 职责与边界

**做什么**

- 查看 / 编辑个人资料（昵称、简介）
- 上传 / 更换头像
- 修改密码（凭旧密码）
- 修改邮箱（发确认邮件 → 点链接生效）
- 邮箱唯一性检测
- 后台：用户列表、创建、启用/禁用、删除

**不做什么**

- 不签发 Token（登录相关全在 01-auth）
- 不管文章、评论（只被它们引用）

---

## 2. 目录结构

```
app/
├── api/v1/user.py                    # UserController（前台 8 条）
├── api/v1/admin/users.py             # AdminUserController（后台 4 条）
├── services/user/
│   └── user_service.py               # UserService
├── repositories/user_repository.py   # UserRepository（资料视角）
└── schemas/user.py
```

---

## 3. 类设计

### 3.1 `UserController` / `AdminUserController`

```python
class UserController:
    """个人中心接口。

    与 AdminUserController 分开两个类而不是一个类挂两套路由：
    两者的鉴权级别、参数来源、响应字段都不同（前台看自己的，后台看别人的），
    混在一起只会让每个方法开头都写 if is_admin。
    """

    def __init__(self, service: UserService) -> None: ...

    def router(self) -> APIRouter:
        """挂载 /user 下的路由。

        注意 /user/email 这条要注册在**无鉴权**的 router 上：
        它是邮件里的确认链接，用户点开时浏览器不带 Authorization 头。
        """

    async def get_info(self, current: CurrentUser) -> JSONResponse: ...
    async def update_profile(self, req: UpdateProfileRequest, current: CurrentUser) -> JSONResponse: ...
    async def update_avatar(self, file: UploadFile, current: CurrentUser) -> JSONResponse: ...
    async def update_password(self, req: UpdatePasswordRequest, current: CurrentUser) -> JSONResponse: ...
    async def request_email_change(self, req: UpdateEmailRequest, current: CurrentUser) -> JSONResponse: ...
    async def add_email(self, req: AddEmailRequest, current: CurrentUser) -> JSONResponse: ...
    async def is_exists_email(self, email: str) -> JSONResponse: ...
    async def confirm_email(self, token: str) -> HTMLResponse:
        """邮件确认链接的落地接口。

        **返回 HTML 页面而不是 JSON**：这个 URL 是给浏览器直接打开的
        （用户点邮件里的按钮），页面自带内联样式，不依赖前端 SPA。
        四种情况（成功 / 缺 token / token 无效 / token 已用）全部返回 HTTP 200，
        成败只体现在页面内容上。

        token 里含 user_id 与**新邮箱**。注意 Go 版把新邮箱塞在 claims 的
        `username` 字段里（历史包袱），Python 侧按同样语义解析，不要被字段名误导。
        """

class AdminUserController:
    """后台用户管理。整组要求 role_id == 1。"""

    async def list_users(self, query: AdminUserQuery) -> JSONResponse: ...
    async def create_user(self, req: AdminCreateUserRequest) -> JSONResponse: ...
    async def update_status(self, user_id: int, req: AdminUpdateUserRequest) -> JSONResponse: ...
    async def delete_user(self, user_id: int) -> JSONResponse: ...
```

### 3.2 `UserService`

```python
class UserService:
    """用户资料与账号设置。

    依赖 AuthService 的两个能力：验证邮箱验证码、校验密码。
    这两个能力只在认证模块实现过，不要在这里复制一份 —— 复制就意味着
    「验证码用途错了」「密码校验规则改了」这类问题要改两处。
    """

    def __init__(
        self,
        repo: UserRepository,
        auth_service: AuthService,
        storage: SupportsFileStorage,
        mailer: EmailSender,
        hasher: PasswordHasher,
        jwt: JWTManager,
        cache: AuthCache,
        settings: Settings,
    ) -> None: ...

    async def get_info(self, user_id: int) -> UserInfoResponse: ...

    async def update_profile(self, user_id: int, req: UpdateProfileRequest) -> None:
        """更新昵称与简介。

        本轮修掉 Go 版的两个问题（详见 8.1）：

        1. **昵称先查重**：排除自己之后再判重，冲突返回 409。
           Go 版直接 UPDATE，撞唯一索引会被兜底成 500「服务器内部错误」。
        2. **区分「不传」与「传空」**：`None` 表示不修改，`""` 表示清空。
           Go 版用 `!= ""` 判断，导致简介永远清不掉。
        """

    async def update_avatar(self, user_id: int, file: UploadFile) -> UpdateAvatarResponse:
        """上传头像。

        流程：校验大小/格式 → 传 MinIO → 拿 key → 更新 users.avatar_url → 删旧文件。
        删旧文件失败只记日志不报错：图片已经换成了，不能因为清理失败让用户以为没成功。
        """

    async def update_password(self, user_id: int, req: UpdatePasswordRequest) -> None:
        """凭旧密码改新密码。

        改完**不踢下线**：旧 access token 15 分钟后自然失效。
        （Go 版本也是这样，保持一致）
        """

    async def request_email_change(self, user_id: int, req: UpdateEmailRequest) -> UpdateEmailResponse:
        """申请换绑邮箱。

        这个接口本身不改库：验证当前密码 + 邮箱验证码 → 给**新邮箱**发一封带
        JWT 的确认链接（5 分钟有效）→ 用户点链接才真正写库。
        这样能证明「新邮箱确实属于本人」。
        """

    async def confirm_email(self, token: str) -> None:
        """确认换绑（邮件链接落地）。

        token 用一次即作废：写入 Redis 黑名单（TTL 300 秒，与 token 同寿）。
        不写黑名单的话，链接在有效期内可以被重复点击，虽然结果一样但会重复写库。

        Raises:
            BizError: token 在黑名单里(403) / 签名无效或已过期(401)。
            异常由 Controller 捕获后渲染成 HTML 失败页，不返回 JSON。

        服务层只管「改没改成功」，页面长什么样是 Controller 的事 ——
        这样将来要换样式，不用动业务逻辑。
        """

    async def add_email(self, user_id: int, req: AddEmailRequest) -> None:
        """给从没绑过邮箱的账号补充邮箱。直接生效，不走确认链接。

        Raises:
            BizError: 账号已有邮箱(403「用户已存在邮箱，不可再添加」) /
                      验证码错误(400) / 邮箱已被占用(409)。
        """

    async def is_exists_email(self, email: str) -> IsExistsResponse: ...

    # ===== 后台 =====
    async def admin_list(self, query: AdminUserQuery) -> AdminUserListResponse: ...
    async def admin_create(self, req: AdminCreateUserRequest) -> int: ...
    async def admin_update_status(self, user_id: int, status: int) -> None: ...
    async def admin_delete(self, user_id: int) -> None:
        """软删除。不清理该用户的文章与评论 —— 历史内容保留，作者显示为空。"""
```

### 3.3 `UserRepository`

```python
class UserRepository:
    """users 表的资料视角查询。

    与 AuthRepository 的分工：这里管 avatar / introduction / 后台列表分页；
    AuthRepository 只管账号、密码、状态这类认证必需字段。
    """

    async def find_by_id(self, user_id: int) -> User | None: ...
    async def find_by_email(self, email: str) -> User | None: ...
    async def update_fields(self, user_id: int, **fields: Any) -> None:
        """局部更新。用 dict 而不是整对象 update，避免把没传的字段覆盖成 None。"""
    async def exists_email(self, email: str) -> bool: ...
    async def paginate(self, page: int, page_size: int, keyword: str, status: int | None) -> tuple[list[User], int]: ...
```

---

## 4. 数据模型

`users` 表完整结构（MySQL 8，`utf8mb4_0900_ai_ci`）：

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | `BIGINT` | PK, AUTO_INCREMENT | |
| `user_name` | `VARCHAR(50)` | NOT NULL, UNIQUE | 昵称，业务限 1-15 字符 |
| `account` | `VARCHAR(50)` | NOT NULL, UNIQUE | 11 位数字 |
| `password_hash` | `VARCHAR(255)` | NOT NULL | bcrypt |
| `email` | `VARCHAR(50)` | NULL | 可空 |
| `introduction` | `TEXT` | NULL | 个人简介 |
| `avatar_url` | `VARCHAR(255)` | NULL | 存 MinIO 的 object key，不是完整 URL |
| `status` | `SMALLINT` | NOT NULL, DEFAULT 1 | 1 启用 / 0 禁用 |
| `role_id` | `SMALLINT` | NOT NULL, DEFAULT 0 | 1 管理员 / 0 普通 |
| `created_at` | `DATETIME` | NOT NULL | |
| `updated_at` | `DATETIME` | NOT NULL | |
| `deleted_at` | `DATETIME` | NULL, INDEX | 软删除 |

**索引**

| 名称 | 列 | 类型 |
|---|---|---|
| PRIMARY | `id` | 主键 |
| uk_user_name | `user_name` | 唯一 |
| uk_account | `account` | 唯一 |
| idx_deleted_at | `deleted_at` | 普通 |

> `avatar_url` 存的是 MinIO object key（如 `all/20261109/ab12cd.jpg`），
> 响应时才拼成完整 URL。存完整 URL 的话，换域名/换 bucket 要全表 UPDATE。

---

## 5. 核心流程

### 5.1 换头像

```
POST /user/avatar (multipart)
 → 校验 size <= 10 MB
 → 校验扩展名 ∈ {.jpg,.jpeg,.png,.webp}
 → object_name = all/{YYYYMMDD}/{random16}{ext}
 → MinIO put
 → UPDATE users SET avatar_url = object_name WHERE id = ?
 → 若旧 avatar_url 非空 → MinIO remove（失败只 warn）
 → 返回 {avatar_url: 完整URL}
```

### 5.2 换绑邮箱（两段式）

```
阶段一：申请
POST /user/email_ack {password, captcha, new_email}
 → 验证 captcha（purpose=reset_email）
 → 验证 password
 → 新邮箱未被占用
 → token = JWT{sub: user_id, email: new_email, exp: 5min}
 → Redis SETNX captcha:limit:{new_email} 60   ← 防连点
 → 发送确认邮件到新邮箱（链接带 token）
 → 返回「已发送确认邮件到新邮箱，请到邮箱确认」

阶段二：确认
GET /user/email?token=xxx   （浏览器直接打开，无 Authorization）
 → 校验 token 签名与有效期
 → Redis 查 blacklist:token:{token}
     └─ 存在 → 403「该token已无效」
 → UPDATE users SET email = token.email
 → Redis SETEX blacklist:token:{token} 300 1
 → 返回「邮箱修改成功」
```

### 5.3 修改密码

```
POST /user/password {old_password, new_password, ack}
 → new != ack → 400
 → verify(old_password, hash) 失败 → 400「密码错误」
 → 校验新密码格式（同注册规则）
 → UPDATE password_hash
```

### 5.4 后台禁用用户

```
PUT /admin/users/:id {status: 0}
 → 不能禁用自己（user_id == current.id → 400）
 → UPDATE status
```

---

## 6. 错误码

| 场景 | code | message |
|---|---|---|
| 用户不存在 | 404 | 用户不存在 |
| 昵称已被占用 | 409 | 该昵称已经存在 |
| 邮箱已被绑定 | 409 | 该邮箱已经被绑定 |
| 账号已有邮箱（补绑时） | 403 | 用户已存在邮箱，不可再添加 |
| 密码错误 | 400 | 密码错误 |
| 两次密码不一致 | 400 | 两次密码不一致 |
| 图片超过 10 MB | 400 | 图片大小不能超过 10MB |
| 不支持的图片格式 | 400 | 不支持的文件格式 |
| 发确认邮件过于频繁 | 429 | 请勿频繁发送验证码，请60秒后再试 |
| 不能禁用自己 | 400 | 不能修改自己的状态 |

> 换绑邮箱的确认链接不是 JSON 接口，失败时渲染 HTML 页面（HTTP 200），
> 页面文案见 [api.md 第 8 节](./api.md#8-确认换绑邮箱邮件链接)。

---

## 7. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 上传 11 MB 图片 | 400「图片大小不能超过 10MB」 |
| 2 | 上传 `.gif` | 400「不支持的文件格式」 |
| 3 | 上传 `.JPG`（大写扩展名） | 通过（转小写后判断） |
| 4 | 换头像后旧对象被删 | MinIO 里只剩新 key |
| 5 | 昵称改成自己现在的昵称 | 成功，不报「已存在」 |
| 6 | 换绑邮箱 token 用第二次 | 403 |
| 7 | 换绑邮箱 token 过期 5 分钟后 | 401 / 403 |
| 8 | 管理员禁用自己 | 400 |
| 9 | 软删除用户后 | 列表查不到，但该用户的文章还在 |
| 10 | `avatar_url` 为空 | 响应返回 `""`，不是 null |

---

## 8. 开放问题

### 8.1 本轮修正的两个历史问题

| # | 问题 | Go 版现状 | 本轮做法 |
|---|---|---|---|
| 1 | 昵称撞唯一索引 | 直接 UPDATE，撞索引抛 DB 异常，被兜底成 500 | 先查重（排除自己）→ 冲突返回 409「该昵称已经存在」 |
| 2 | 简介无法清空 | 字段传 `""` 被当成「不修改」 | 入参用 `str \| None`：`None` = 不改，`""` = 清空 |

> 两处**不影响响应结构**，只改内部行为，前端调用方式不变。

### 8.2 其他

1. **删除用户是否级联**：Go 版软删用户后，其文章、评论都留着，作者名显示为空。
   是否接受？（建议接受，这是博客的常规做法）
2. **`user_name` 允许改**：改了之后，历史评论里的 `reply_to_name` 是快照，不会跟着变。
   是否要同步更新？建议不更新（评论显示的是当时的名字）。
3. **后台删用户用的是软删**：`deleted_at` 有值但 `account` 仍占着唯一索引，
   同一账号无法重新注册。是否需要真删或改写 account？建议保持，避免误删后账号被抢注。
