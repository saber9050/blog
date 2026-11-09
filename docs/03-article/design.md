# 03 文章模块 · 设计方案

## 1. 职责与边界

**做什么**

- 前台：文章列表（筛选 / 排序 / 分页）、详情（浏览量 +1）、随机一篇、站点统计、点赞 / 取消点赞
- 后台：文章列表、创建、更新、删除（连带清理图片与评论）、批量转移分类、图片上传
- 维护 `article_images` 表：正文里引用的图片与文章的关联关系

**不做什么**

- 不生成摘要（调 07-llm 的 `SummaryService`）
- 不管分类/标签本身的增删改（05-taxonomy）
- 不管评论内容（04-comment），只在删文章时软删其评论

---

## 2. 目录结构

```
app/
├── api/v1/articles.py                # ArticleController（前台 6 条）
├── api/v1/admin/articles.py          # AdminArticleController（后台 6 条，摘要接口在 07）
├── services/article/
│   ├── article_service.py            # ArticleService：前台读 + 点赞
│   ├── article_admin_service.py      # ArticleAdminService：后台写
│   └── article_assembler.py          # ArticleAssembler：实体 → 响应 DTO（解决 N+1）
├── repositories/
│   ├── article_repository.py
│   ├── article_image_repository.py
│   └── like_repository.py
└── schemas/article.py
```

> **为什么拆三个 Service**：Go 版是单个 `articleService`（705 行）什么都干。
> 前台读、后台写、DTO 组装三块耦合在一起，改一处要通读全文。
> 拆开后 `ArticleAssembler` 是唯一的组装入口，N+1 优化只在这里实现一次。

---

## 3. 类设计

### 3.1 `ArticleAssembler`（核心）

```python
class ArticleAssembler:
    """把 Article 实体组装成列表项 DTO。

    ⚠️ 这里承载本模块唯一的重构点：
    Go 版每篇文章要单独查 6 次（作者 / 分类 / 标签 / 是否点赞 / 点赞数 / 评论数），
    一页 10 篇就是 60 次查询。这里改成批量：
      1. 一次性收集所有 user_id / type_id / article_id
      2. 用 IN 查询把这几个维度全部捞回来
      3. 在内存里拼装
    一页 10 篇的总查询数固定为 6 条（含主查询），与页大小无关。
    """

    def __init__(
        self,
        user_repo: UserRepository,
        category_repo: CategoryRepository,
        tag_repo: TagRepository,
        article_repo: ArticleRepository,
        like_repo: LikeRepository,
        comment_repo: CommentRepository,
        storage: SupportsFileStorage,
    ) -> None: ...

    async def build_many(
        self, articles: Sequence[Article], viewer_id: int | None
    ) -> list[ArticleItem]:
        """批量组装列表项。

        Args:
            articles: 当前页的文章实体。
            viewer_id: 当前登录用户 ID；游客传 None，此时 is_liked 恒为 False。

        Returns:
            与输入顺序一致的 ArticleItem 列表。
        """

    async def build_one(self, article: Article, viewer_id: int | None) -> ArticleItem:
        """组装单篇（详情页用）。内部复用 build_many，避免两套逻辑。"""
```

### 3.2 `ArticleService`（前台）

```python
class ArticleService:
    """前台阅读相关。

    只读 + 点赞。所有写操作在 ArticleAdminService。
    """

    def __init__(
        self,
        repo: ArticleRepository,
        like_repo: LikeRepository,
        assembler: ArticleAssembler,
        user_repo: UserRepository,
    ) -> None: ...

    async def list_public(self, query: ArticleListQuery, viewer_id: int | None) -> ArticleListResponse:
        """前台文章列表。

        固定过滤 status=1（已发布）与 deleted_at IS NULL。
        排序：默认 created_at DESC；sort=popular 时按热度公式。
        """

    async def get_detail(self, article_id: int, viewer_id: int | None) -> ArticleDetailResponse:
        """文章详情。

        每次调用浏览量 +1。用 UPDATE ... SET views = views + 1 原子自增，
        不用「读出来 +1 再写回」—— 后者并发下会丢计数。
        """

    async def get_random_id(self) -> int:
        """随机取一篇已发布文章的 ID。用 ORDER BY RAND() 在有索引的小表上可接受，
        数据量大了要换成「随机 offset」。"""

    async def get_stats(self) -> ArticleStatsResponse:
        """站点统计：文章数、总浏览量、总点赞数。三条聚合查询，不走缓存。"""

    async def like(self, article_id: int, user_id: int) -> None:
        """点赞。

        ⚠️ likes 表没有唯一索引，靠「先查后插」。并发双击会插两条重复记录。
        这是 Go 版的现状，本轮**保持不改**（加唯一索引需要改表结构，
        且前端已用 is_liked 布尔判断，重复记录不会导致 UI 错乱，只会让计数虚高）。
        """

    async def unlike(self, article_id: int, user_id: int) -> None: ...
```

### 3.3 `ArticleAdminService`（后台）

```python
class ArticleAdminService:
    """后台文章写操作。

    之所以和 ArticleService 分开：这个类的方法全部在事务里跑，
    且都要处理 MinIO 的补偿逻辑；前台那几个方法一条写都没有，混在一起容易误用。
    """

    def __init__(
        self,
        repo: ArticleRepository,
        image_repo: ArticleImageRepository,
        asm_assembler: ArticleAssembler,
        comment_repo: CommentRepository,
        category_repo: CategoryRepository,
        tag_repo: TagRepository,
        storage: SupportsFileStorage,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None: ...

    async def list(self, query: AdminArticleQuery) -> AdminArticleListResponse:
        """后台列表。不过滤 status，但要带 deleted_at IS NULL。"""

    async def create(self, req: CreateArticleRequest, author_id: int) -> int:
        """新建文章。

        步骤（顺序不能变）：
          1. 校验分类存在
          2. 封面 URL → object key（前端传完整 URL，库里存 key）
          3. INSERT articles
          4. 关联标签（先删后插，或仅插入）
          5. 解析正文 <img> → 同步 article_images（差集）
        第 5 步失败不回滚文章：文字内容比图片引用重要，图挂了可以再编辑修。
        """

    async def update(self, article_id: int, req: UpdateArticleRequest) -> None:
        """更新文章。

        注意：更新不重算摘要。摘要由用户在编辑器里手动点「生成」。
        """

    async def delete(self, article_id: int) -> None:
        """删除文章（软删）+ 清理资源。

        顺序：
          1. 查 article_images → 逐张删 MinIO → 删表记录
          2. 删封面图
          3. 软删该文章下所有评论
          4. 软删文章
        MinIO 删除失败只记日志不中断：宁可留几张孤儿图，也不能让文章删不掉。
        """

    async def transfer_category(self, from_id: int, to_id: int) -> int:
        """批量把 A 分类下的文章转到 B 分类，返回受影响行数。"""

    async def upload_image(self, file: UploadFile) -> str:
        """上传图片，返回完整 URL。

        规则与头像一致（10 MB、4 种扩展名），复用 UserService.upload_image 的校验，
        但对象前缀是 all/{date}/ 而不是 avatar/。
        """
```

### 3.4 仓储

```python
class ArticleRepository:
    """articles 表访问。

    所有查询方法内部强制拼 not_deleted(Article)，不接受调用方传参决定是否过滤 ——
    软删除是硬约束，不该给调用方留关掉的口子。
    """

    async def paginate(self, ...) -> tuple[list[Article], int]: ...
    async def find_by_id(self, article_id: int) -> Article | None: ...
    async def increment_views(self, article_id: int) -> None: ...
    async def insert(self, article: Article) -> int: ...
    async def update_fields(self, article_id: int, **fields: Any) -> None: ...
    async def soft_delete(self, article_id: int) -> None: ...
    async def list_ids_by_category(self, category_id: int) -> list[int]: ...

class LikeRepository:
    """likes 表访问。"""
    async def is_liked(self, article_id: int, user_id: int) -> bool: ...
    async def liked_ids(self, user_id: int, article_ids: Sequence[int]) -> set[int]:
        """批量判断哪些文章被该用户点过赞。一次 IN 查询，避免 N+1。"""
    async def count_by_articles(self, article_ids: Sequence[int]) -> dict[int, int]:
        """批量统计点赞数。GROUP BY article_id，一次查询。"""
    async def add(self, article_id: int, user_id: int) -> None: ...
    async def remove(self, article_id: int, user_id: int) -> None: ...

class ArticleImageRepository:
    """article_images 表访问。用于删除文章时清理图片。"""
    async def list_by_article(self, article_id: int) -> list[ArticleImage]: ...
    async def replace(self, article_id: int, keys: set[str]) -> None:
        """差集同步：新增缺失的、删除多余的。"""
```

---

## 4. 数据模型

### 4.1 `articles`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | `BIGINT` | PK | |
| `user_id` | `BIGINT` | NOT NULL | 作者 |
| `title` | `VARCHAR(100)` | NOT NULL | 标题 |
| `content` | `MEDIUMTEXT` | NOT NULL | Markdown 正文，上限 16 MB |
| `cover_url` | `VARCHAR(255)` | NULL | **存 object key**，不是完整 URL |
| `summary` | `VARCHAR(255)` | NULL | AI 生成的摘要，超 255 会截断 |
| `views` | `BIGINT` | NOT NULL DEFAULT 0 | 浏览量 |
| `type_id` | `BIGINT` | NOT NULL | 分类 ID |
| `status` | `SMALLINT` | NOT NULL DEFAULT 0 | 1 发布 / 0 草稿 |
| `created_at` / `updated_at` | `DATETIME` | NOT NULL | |
| `deleted_at` | `DATETIME` | NULL, INDEX | 软删除 |

**索引**

| 名称 | 列 | 说明 |
|---|---|---|
| PRIMARY | `id` | |
| idx_type_status | `type_id`, `status` | 分类页列表 |
| idx_status_created | `status`, `created_at` | 前台默认排序 |
| idx_deleted_at | `deleted_at` | |

> 与 Go 版的差异：**不再有 4 个 `vector_*` 列**（向量功能已删除）。
> 后台列表接口也不再返回这些字段。

### 4.2 `article_images`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT` | |
| `article_id` | `BIGINT` NOT NULL, INDEX | |
| `url` | `VARCHAR(255)` | 存 object key |

### 4.3 `likes`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT` | |
| `article_id` | `BIGINT` NOT NULL, INDEX | |
| `user_id` | `BIGINT` NOT NULL, INDEX | |

> **没有唯一索引**（照抄 Go 版）。`(article_id, user_id)` 加唯一键是技术债，
> 见第 8 节开放问题。

---

## 5. 核心流程

### 5.1 前台列表（N+1 修复的关键）

```
GET /articles?page=1&page_size=10&sort=popular&category_id=3&tag_ids=1,2&keyword=go

① SELECT ... FROM articles
   WHERE status = 1 AND deleted_at IS NULL
     [AND type_id = 3]
     [AND (title LIKE '%go%' OR summary LIKE '%go%')]
     [AND id IN (SELECT article_id FROM tag_articles WHERE tag_id IN (1,2) GROUP BY article_id)]
   ORDER BY <created_at DESC | 热度公式 DESC>
   LIMIT 10 OFFSET 0
② SELECT count(*) —— 同条件的总数
③ SELECT * FROM users WHERE id IN (...作者ID)          ← 1 条
④ SELECT * FROM categorys WHERE id IN (...分类ID)      ← 1 条
⑤ SELECT ta.article_id, t.* FROM tag_articles ta JOIN tags t
     ON t.id = ta.tag_id WHERE ta.article_id IN (...)  ← 1 条
⑥ SELECT article_id, count(*) FROM likes WHERE article_id IN (...) GROUP BY article_id  ← 1 条
⑦ SELECT article_id, count(*) FROM comments
     WHERE article_id IN (...) AND deleted_at IS NULL GROUP BY article_id  ← 1 条
⑧ [登录时] SELECT article_id FROM likes WHERE user_id = ? AND article_id IN (...)  ← 1 条

内存拼装 → ArticleItem[]
```

固定 8 条查询，与页大小无关。Go 版是 1 + 10×6 = 61 条。

### 5.2 热度排序公式（照抄）

```
score = like_count * 3 + views * 1 + comment_count * 2
ORDER BY score DESC
```

MySQL 下写成：

```sql
ORDER BY (
  (SELECT COUNT(*) FROM likes WHERE likes.article_id = articles.id) * 3
  + articles.views
  + (SELECT COUNT(*) FROM comments
     WHERE comments.article_id = articles.id AND comments.deleted_at IS NULL) * 2
) DESC
```

### 5.3 详情

```
GET /articles/:id
 → SELECT ... WHERE id = ? AND deleted_at IS NULL
     └─ 不存在 → 404
 → UPDATE articles SET views = views + 1 WHERE id = ?   ← 不等待结果，失败只记日志
 → 组装（复用 build_one）
 → 返回（含 content）
```

### 5.4 点赞 / 取消

```
POST /articles/:id/like
 → 用户存在且 status=1（禁用用户不能点赞）
 → 文章存在且 deleted_at IS NULL
 → is_liked?
     ├─ 已点赞 → 400「您已经点赞过该文章」
     └─ 未点赞 → INSERT likes
DELETE /articles/:id/like
 → is_liked?
     ├─ 未点赞 → 400「您尚未点赞该文章」
     └─ 已点赞 → DELETE likes WHERE article_id = ? AND user_id = ?
```

### 5.5 创建文章

```
POST /admin/articles
 → 校验分类存在（type_id 指向有效分类）
 → cover_url 完整 URL → object key（失败 → 500「解析url失败」）
 → INSERT articles(user_id=当前管理员, status=req.status)
 → 标签：DELETE tag_articles WHERE article_id=? ; INSERT 新关联
 → 正文图片同步：
     extract_img_src(content) → [完整URL...]
       └─ 空列表 → 跳过（保留已有记录）
     parse_file_key(url) → {key...}（解析失败的跳过并 warn）
     旧记录 - 新集合 → 删 MinIO + 删表
     新集合 - 旧记录 → 插表
 → 返回 {id}
```

### 5.6 删除文章

```
DELETE /admin/articles/:id
 → 查文章（不存在 → 404）
 → 查 article_images
     └─ 逐张 MinIO delete（失败 warn）→ 删 article_images 记录
 → 有 cover_url → MinIO delete（失败 warn）
 → 软删该文章所有评论（UPDATE comments SET deleted_at = now() WHERE article_id = ?）
 → 软删文章
```

**没有事务包裹整个过程**：MinIO 操作不可回滚，硬套事务只会让「图片删了、文章没删」更难查。
顺序设计成「先删资源后删记录」，最坏情况是留几张孤儿图，不会出现「文章没了图还在引用」的破页面。

---

## 6. 错误码

| 场景 | code | message |
|---|---|---|
| 文章不存在 | 404 | 文章不存在 |
| 分类不存在 | 400 | 分类不存在 |
| 已点赞 | 400 | 您已经点赞过该文章 |
| 未点赞 | 400 | 您尚未点赞该文章 |
| 用户被封禁 | 403 | 该用户已被封禁 |
| 图片超限 | 400 | 图片大小不能超过 10MB |
| 格式不支持 | 400 | 不支持的文件格式 |
| 封面 URL 解析失败 | 500 | 解析url失败 |
| 无文章可随机 | 404 | 暂无文章 |

---

## 7. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 列表查询的 SQL 条数 | 一页 10 篇，总查询数 = 8（不随页大小增长） |
| 2 | 已删文章不出现在列表 | 软删后立刻查不到 |
| 3 | 草稿不出现在前台 | `status=0` 只能后台看到 |
| 4 | 热度排序 | 点赞多的排在前面（likes 权重 3 > comments 2 > views 1） |
| 5 | 详情浏览量 | 连请求 3 次，`views` +3 |
| 6 | 重复点赞 | 第二次 400 |
| 7 | 禁用用户点赞 | 403 |
| 8 | 正文含 3 张图，编辑后删掉 1 张 | `article_images` 只剩 2 条，MinIO 少 1 个对象 |
| 9 | 正文改为无图 | **不清空**已有记录（Go 的刻意行为） |
| 10 | 删除文章 | 评论被软删、图片被删、文章软删 |
| 11 | 3 万字正文 | 入库后 `char_length(content)` = 30000，不截断 |
| 12 | 上传 11 MB 图 | 400 |

---

## 8. 开放问题

1. **`likes` 缺唯一索引**：并发双击会产生重复记录，点赞数虚高。
   建议加 `UNIQUE(article_id, user_id)`。要加的话在 P0 建表时就加，后面补要清数据。
   **需要你拍板。**
2. **随机文章用 `ORDER BY RAND()`**：文章上万后会很慢。当前 19 篇无所谓，建议先这样。
3. **删文章不删评论记录，只软删**：评论表会累积。是否需要定期清理？建议不做。
4. **`syncArticleImages` 的「空图不清空」行为**：正文里的图全删掉后，`article_images`
   仍保留旧记录，导致删文章时会去删已经不在正文里的图。
   Go 版这么写是有意的（防止误删刚上传还没插入正文的图），本轮照抄。
5. **`ArticleItem` 的 `created_at` 是 `string`**，其他模块有的是 `time.Time`（评论）。
   这是 Go 版的不一致，本轮照抄，不统一。
