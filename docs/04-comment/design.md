# 04 评论模块 · 设计方案

## 1. 职责与边界

**做什么**

- 一级评论列表（分页，带子回复数）
- 二级回复列表（分页）
- 发表评论 / 回复
- 删除评论（作者或管理员）
- 后台：评论列表（按文章标题 / 用户名 / 时间筛选）、单条删除、批量删除

**不做什么**

- 不做多级嵌套（只有两级：`parent_id` 为空 = 一级，有值 = 二级）
- 不做点赞、举报、审核状态

---

## 2. 目录结构

```
app/
├── api/v1/comments.py                # CommentController（前台 4 条）
├── api/v1/admin/comments.py          # AdminCommentController（后台 3 条）
├── services/comment_service.py       # CommentService
├── repositories/comment_repository.py
└── schemas/comment.py
```

---

## 3. 类设计

### 3.1 `CommentController`

```python
class CommentController:
    """评论接口。

    路由挂在 /articles 下（不是 /comments），因为评论天然从属于文章：
    /articles/{id}/comments 比 /comments?article_id= 更清晰，且能复用路径参数。
    """

    def __init__(self, service: CommentService) -> None: ...

    def router(self) -> APIRouter: ...

    async def list_comments(self, article_id: int, page: int, page_size: int) -> JSONResponse: ...
    async def list_replies(self, article_id: int, comment_id: int, page: int, page_size: int) -> JSONResponse: ...
    async def create(self, article_id: int, req: CreateCommentRequest, current: CurrentUser) -> JSONResponse: ...
    async def delete(self, article_id: int, comment_id: int, current: CurrentUser) -> JSONResponse: ...
```

### 3.2 `CommentService`

```python
class CommentService:
    """评论业务。"""

    def __init__(
        self,
        repo: CommentRepository,
        user_repo: UserRepository,
        article_repo: ArticleRepository,
        storage: SupportsFileStorage,
    ) -> None: ...

    async def list_comments(self, article_id: int, page: int, page_size: int) -> CommentListResponse:
        """一级评论列表。

        分页规则：page 默认 1，page_size 默认 20、上限 50。
        需要额外统计每条评论的子回复数（一次 GROUP BY，不要循环 count）。
        """

    async def list_replies(self, parent_id: int, page: int, page_size: int) -> CommentListResponse:
        """某条一级评论下的回复。

        分页规则与一级不同：page_size 默认 10、上限 30。
        这个差异是历史原因，前端已按各自默认值写死，不要统一。
        """

    async def create(self, article_id: int, user_id: int, req: CreateCommentRequest) -> CommentItem:
        """发表评论或回复。

        校验链：
          1. 内容非空
          2. 用户存在且未被禁用
          3. 若是回复：父评论存在，且 parent.article_id == 当前文章 ID
             （防止把回复挂到别的文章下，造成跨文章串评论）
        返回体包含用户名与头像，前端直接追加到列表，不用再查。
        """

    async def delete(self, comment_id: int, current: CurrentUser) -> None:
        """删除评论。作者本人或管理员可删。

        **本轮改为级联软删**：删一级评论时，一并软删它下面的所有回复
        （`parent_id = comment_id`）。

        Go 版只删一级，子回复留在库里，`parent_id` 指向一条已删记录 ——
        界面上看不见它们（一级列表不返回），但它们会继续计入 total、
        在后台列表里出现，越积越脏。

        Raises:
            BizError: 评论不存在(404) / 无权限(403)。
        """

    # ===== 后台 =====
    async def admin_list(self, query: AdminCommentQuery) -> PaginatedResponse:
        """后台评论列表。需要 JOIN articles 拿文章标题、JOIN users 拿用户名。"""

    async def admin_delete(self, comment_id: int) -> None: ...

    async def admin_batch_delete(self, ids: Sequence[int]) -> int:
        """批量删除，返回实际删除条数。空列表直接返回 0，不要报错。"""
```

### 3.3 `CommentRepository`

```python
class CommentRepository:
    """comments 表访问。

    与其他仓储不同，这里的查询需要「包含已删除记录」：
    已删除的评论仍要在列表里占位（前端显示「该评论已被删除」），
    所以不能无脑加 not_deleted() 过滤。

    ⚠️ **total 与列表必须口径一致，都包含已删**。
    Go 版这里有个 bug：计数用 `Model(&Comment{})`，GORM 会自动加
    `deleted_at IS NULL`；而列表用 `Table("comments")`，GORM 不认识模型、
    不加任何软删条件。结果就是「total=3，列表渲染出 5 条」，前端分页器错位。

    修法不能是「让列表也不含已删」—— 那样 is_deleted 永远是 false，
    前端「该评论已删除」的占位逻辑就废了。正确做法是两处都不加过滤。
    """

    async def paginate_top_level(self, article_id: int, page: int, page_size: int) -> tuple[list[Comment], int]:
        """一级评论：parent_id 为空或 0。

        列表与 total **都包含已删除记录**，保持一致。
        """

    async def paginate_replies(self, parent_id: int, page: int, page_size: int) -> tuple[list[Comment], int]: ...

    async def count_children(self, parent_ids: Sequence[int]) -> dict[int, int]:
        """批量统计子回复数。一次 GROUP BY，避免每条评论查一次。"""

    async def find_by_id(self, comment_id: int, include_deleted: bool = False) -> Comment | None: ...

    async def insert(self, comment: Comment) -> int: ...

    async def soft_delete(self, comment_id: int) -> None:
        """软删单条。"""

    async def soft_delete_with_replies(self, comment_id: int) -> int:
        """软删一条一级评论及其所有回复。

        一条 UPDATE 解决，不要先查子 ID 再逐条删：
            UPDATE comments SET deleted_at = NOW()
            WHERE id = ? OR parent_id = ?
        返回影响行数，便于日志里看出连带删了几条。
        """

    async def soft_delete_by_article(self, article_id: int) -> int:
        """软删某篇文章下所有评论。删文章时调用，返回影响行数。"""

    async def batch_soft_delete(self, ids: Sequence[int]) -> int: ...

    async def paginate_admin(self, query: AdminCommentQuery) -> tuple[list[AdminCommentRow], int]: ...
```

---

## 4. 数据模型

### `comments`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | `BIGINT` | PK | |
| `article_id` | `BIGINT` | NOT NULL, INDEX | |
| `user_id` | `BIGINT` | NOT NULL, INDEX | |
| `parent_id` | `BIGINT` | NULL, INDEX | 空/0 = 一级；有值 = 回复 |
| `content` | `TEXT` | NOT NULL | 评论内容 |
| `reply_to_name` | `VARCHAR(100)` | DEFAULT '' | 回复目标用户名（**快照**，不随改名变化） |
| `created_at` / `updated_at` | `DATETIME` | NOT NULL | |
| `deleted_at` | `DATETIME` | NULL, INDEX | 软删除 |

**索引**

| 名称 | 列 | 用途 |
|---|---|---|
| PRIMARY | `id` | |
| idx_article_parent | `article_id`, `parent_id` | 一级列表 + 回复列表 |
| idx_user | `user_id` | 后台按用户筛 |
| idx_deleted_at | `deleted_at` | |

> `content` 用 `TEXT`（64 KB）够用：评论区不该出现 2 万字。
> 若要限制，业务层加 1000 字符上限更合理，本轮不加以免改变契约。

---

## 5. 核心流程

### 5.1 一级评论列表（带子回复数）

```
GET /articles/12/comments?page=1&page_size=20

① SELECT * FROM comments
   WHERE article_id = 12 AND (parent_id IS NULL OR parent_id = 0)
   ORDER BY created_at DESC
   LIMIT 20 OFFSET 0
   —— 注意：不过滤 deleted_at，已删的也要返回占位
② SELECT count(*) 同条件
③ SELECT parent_id, count(*) FROM comments
   WHERE parent_id IN (...上面 20 条的 id...)
   GROUP BY parent_id
④ 组装：已删除的条目 content 置空、is_deleted = true
```

### 5.2 发表评论

```
POST /articles/12/comments
 → content 非空
 → 用户存在且 status=1
 → 若 parent_id 有值：
     父评论存在（不存在 → 404）
     parent.article_id == 12（否则 400「父评论不属于该文章」）
 → INSERT comments
 → 查当前用户昵称与头像（拼完整 URL）
 → 返回 CommentItem
```

### 5.3 删除评论

```
DELETE /articles/12/comments/34
 → 查评论（含软删记录，否则重复删除会 404 而不是幂等）
 → current.id != comment.user_id 且 current.role_id != 1 → 403
 → UPDATE comments SET deleted_at = now()
```

### 5.4 后台筛选

```
GET /admin/comments?page=1&page_size=10&article_title=xx&user_name=yy&start_time=2026-01-01

SELECT c.*, a.title AS article_title, u.user_name
FROM comments c
LEFT JOIN articles a ON a.id = c.article_id
LEFT JOIN users u ON u.id = c.user_id
WHERE c.deleted_at IS NULL
  [AND a.title LIKE ?] [AND u.user_name LIKE ?] [AND c.created_at BETWEEN ? AND ?]
ORDER BY c.created_at DESC
LIMIT ? OFFSET ?
```

---

## 6. 错误码

| 场景 | code | message |
|---|---|---|
| 内容为空 | 400 | 请求参数错误 |
| 用户不存在 | 404 | 用户不存在 |
| 用户被封禁 | 403 | 该用户已被封禁 |
| 父评论不存在 | 404 | 资源不存在 |
| 父评论不属于该文章 | 400 | 父评论不属于该文章 |
| 评论不存在 | 404 | 资源不存在 |
| 无权删除 | 403 | 禁止访问 |

---

## 7. 开放问题

### 7.1 删除一级评论：本轮级联软删

| 方案 | 行为 | 结论 |
|---|---|---|
| A. 保持 Go 版 | 只软删一级，子回复留库里 | 否决：数据越积越多，后台列表变脏 |
| **B. 级联软删** | 同时软删所有 `parent_id = 该评论` 的回复 | **本轮采用** |
| C. 显示占位 | 一级删了，回复仍显示 | 否决：需要改前端 |

B 只在 `CommentService.delete` 里多做一句 UPDATE，前端不用动。
二级回复脱离一级评论后没有上下文，留着也没用。

### 7.2 其他

1. **评论内容无长度上限**：`TEXT` 能存 64 KB。是否加 1000 字符限制？
   加的话前后端都要改提示文案，建议后续迭代。
2. **`reply_to_name` 是快照**：被回复的人改昵称后，评论里显示的仍是旧名。保持现状。
3. **`article.comment_count` 与列表 total 口径不同**：文章列表里的 `comment_count`
   统计的是未删评论（SQL 里带 `deleted_at IS NULL`），而评论列表的 `total` 包含已删占位。
   所以文章卡片显示「3 条评论」，点进去页面写「共 5 条」。

   **本轮统一为「含已删」**：把 `comment_count` 的 SQL 去掉 `deleted_at IS NULL`，
   与列表 total 对齐。这样三处数字一致，前端的「该评论已删除」占位也仍然有效。

   反方向的「都不含已删」不采用：那样 `is_deleted` 永远为 `false`，
   前端的占位展示逻辑直接废掉。
