# 05 分类与标签 · 设计方案

> 分类和标签是两张表、两套接口，但业务逻辑高度同构（名称唯一、启用状态、CRUD、计数）。
> 合并到一个模块文档，代码上用**模板方法模式**共享基类，不做两份复制。

## 1. 职责与边界

**做什么**

- 分类：前台启用列表、后台 CRUD、启用数量统计
- 标签：前台启用列表、后台 CRUD、启用数量统计、删除时清理文章关联
- 被 03-article 引用（文章挂在分类下、可打多个标签）

**不做什么**

- 不管文章筛选逻辑（在 03 的 `ArticleRepository`）
- 不做层级的树形分类（只有一级）

---

## 2. 目录结构

```
app/
├── api/v1/taxonomy/
│   ├── categories.py                 # 前台分类 2 条
│   └── tags.py                       # 前台标签 2 条
├── api/v1/admin/taxonomy/
│   ├── categories.py                 # 后台分类 4 条
│   └── tags.py                       # 后台标签 4 条
├── services/taxonomy/
│   ├── base.py                       # TaxonomyService 抽象基类（模板方法）
│   ├── category_service.py
│   └── tag_service.py
├── repositories/taxonomy/
│   ├── base.py                       # TaxonomyRepository 泛型基类
│   ├── category_repository.py
│   └── tag_repository.py
└── schemas/taxonomy.py
```

---

## 3. 类设计

### 3.1 `TaxonomyService[T]`（抽象基类）

```python
T = TypeVar("T")  # Category | Tag

class TaxonomyService(ABC, Generic[T]):
    """分类/标签的公共业务骨架。

    用模板方法而不是复制两份代码：两者 90% 的逻辑一样，
    剩下的差异（删除前要不要检查文章、要不要先删关联表）通过钩子方法交给子类。

    这样新增一个「专题」实体时，只需要实现三个钩子就能复用整套 CRUD。
    """

    def __init__(self, repo: TaxonomyRepository[T]) -> None:
        self._repo = repo

    # ---------- 公共流程 ----------

    async def list_public(self) -> list[TaxonomyPublicDTO]:
        """前台列表：只返回 status=1，按创建时间正序。"""

    async def count_enabled(self) -> int:
        """启用数量。首页「N 个分类」用。"""

    async def list_admin(self, query: TaxonomyQuery) -> PaginatedResponse:
        """后台分页列表：可按状态、关键词、时间范围筛选。"""

    async def create(self, name: str, status: int) -> int:
        """新建。

        名称查重：`IsExistsByName(name, exclude_id=0)`。
        MySQL 的 ci 排序规则下「后端」与「后端 」算重名（尾空格被忽略），
        所以入库前统一 strip()。
        """

    async def update(self, entity_id: int, name: str, status: int) -> None:
        """更新。查重时排除自己，否则改个大小写都会报「已存在」。"""

    async def delete(self, entity_id: int) -> None:
        """删除。流程固定，差异在钩子里：

        1. 查实体（不存在 → 404）
        2. `await self._before_delete(entity)`   ← 子类实现
        3. 物理删除（这两张表都没有软删除标记）
        """

    # ---------- 交给子类的钩子 ----------

    @abstractmethod
    async def _before_delete(self, entity: T) -> None:
        """删除前的差异化检查与清理。"""
```

### 3.2 `CategoryService`

```python
class CategoryService(TaxonomyService[Category]):
    """分类。

    删除规则比标签严格：分类是文章的唯一归属，删了文章就没地方挂了。
    所以有关联文章时直接拒绝，要求先走「批量转移分类」。
    """

    def __init__(self, repo: CategoryRepository, article_repo: ArticleRepository) -> None:
        super().__init__(repo)
        self._article_repo = article_repo

    async def _before_delete(self, entity: Category) -> None:
        """检查该分类下是否有文章。

        Raises:
            BizError: 有文章时拒绝，提示先转移（400）。
        """
        count = await self._article_repo.count_by_category(entity.id)
        if count > 0:
            raise BizError(ErrorCode.BAD_REQUEST, "该分类下存在文章，无法删除")
```

### 3.3 `TagService`

```python
class TagService(TaxonomyService[Tag]):
    """标签。

    删除比分类宽松：标签只是附加信息，删了不影响文章的归属，
    所以直接清掉关联表后删除，文章本身不动。
    """

    def __init__(self, repo: TagRepository) -> None:
        super().__init__(repo)

    async def _before_delete(self, entity: Tag) -> None:
        """先删 tag_articles 里的关联记录，否则会留下指向不存在标签的脏关联。"""
        await self._repo.delete_article_links(entity.id)
```

### 3.4 `TaxonomyRepository[T]`（泛型基类）

```python
class TaxonomyRepository(ABC, Generic[T]):
    """两张表的公共查询。

    泛型参数是 ORM 模型类；子类只需在 __init__ 里声明 model 与 name_column。
    """

    model: type[T]
    name_column: InstrumentedAttribute[str]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...

    async def find_by_id(self, entity_id: int) -> T | None: ...
    async def exists_name(self, name: str, exclude_id: int = 0) -> bool: ...
    async def paginate(self, query: TaxonomyQuery) -> tuple[list[T], int]: ...
    async def count_enabled(self) -> int: ...
    async def insert(self, entity: T) -> int: ...
    async def update_fields(self, entity_id: int, **fields: Any) -> None: ...
    async def delete(self, entity_id: int) -> None: ...

class CategoryRepository(TaxonomyRepository[Category]):
    model = Category
    name_column = Category.category_name

class TagRepository(TaxonomyRepository[Tag]):
    model = Tag
    name_column = Tag.tag_name

    async def delete_article_links(self, tag_id: int) -> None:
        """DELETE FROM tag_articles WHERE tag_id = ?"""
```

---

## 4. 类关系图

```
TaxonomyService (ABC, Generic[T])
 ├── CategoryService ── CategoryRepository + ArticleRepository（只用于计数）
 └── TagService      ── TagRepository

TaxonomyRepository (ABC, Generic[T])
 ├── CategoryRepository
 └── TagRepository
```

---

## 5. 数据模型

### 5.1 `categorys`（表名就是这个拼写）

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | `BIGINT` | PK | |
| `category_name` | `VARCHAR(50)` | NOT NULL | |
| `status` | `SMALLINT` | NOT NULL | 1 启用 / 0 禁用 |
| `created_at` / `updated_at` | `DATETIME` | NOT NULL | |

> **表名是 `categorys`，不是 `categories`**。Go 版的 `TableName()` 就这么写的，
> 前端 SQL 和文档里都这么引用，照抄别改。

### 5.2 `tags`

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | `BIGINT` | PK |
| `tag_name` | `VARCHAR(100)` | NOT NULL |
| `status` | `SMALLINT` | NOT NULL |
| `created_at` / `updated_at` | `DATETIME` | NOT NULL |

### 5.3 `tag_articles`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT` | PK |
| `article_id` | `BIGINT` NOT NULL, INDEX | |
| `tag_id` | `BIGINT` NOT NULL, INDEX | |

> 三张表都**没有 `deleted_at`**，删除是物理删除。与 articles/comments 不同。
> 也**没有物理外键**，靠代码保证一致性（照抄 Go 版）。

---

## 6. 核心流程

### 6.1 删除分类

```
DELETE /admin/categories/3
 → 查分类 → 不存在 404
 → SELECT count(*) FROM articles WHERE type_id = 3 AND deleted_at IS NULL
     └─ > 0 → 400「该分类下存在文章，无法删除」
 → DELETE FROM categorys WHERE id = 3
```

### 6.2 删除标签

```
DELETE /admin/tags/5
 → 查标签 → 不存在 404
 → DELETE FROM tag_articles WHERE tag_id = 5
 → DELETE FROM tags WHERE id = 5
```

### 6.3 名称查重

```
POST /admin/categories {name: "后端"}
 → strip(name)
 → SELECT 1 FROM categorys WHERE category_name = '后端' LIMIT 1
     └─ 命中 → 400「分类名称已存在」
 → INSERT
```

更新时排除自己：

```
PUT /admin/categories/3 {name: "后端"}
 → SELECT 1 FROM categorys WHERE category_name = '后端' AND id != 3
     └─ 不命中 → 允许（改大小写、改回原名都不报错）
```

---

## 7. 错误码

| 场景 | code | message |
|---|---|---|
| 分类不存在 | 404 | 分类不存在 |
| 标签不存在 | 404 | 标签不存在 |
| 分类名称已存在 | 400 | 分类名称已存在 |
| 标签名称已存在 | 400 | 标签名称已存在 |
| 分类下有文章 | 400 | 该分类下存在文章，无法删除 |
| 名称超长 | 400 | 请求参数错误 |

---

## 8. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 新建重名分类 | 400 |
| 2 | 名称首尾带空格 | 入库前被 strip |
| 3 | 更新分类时名称改成自己原名 | 成功（排除自己） |
| 4 | 删除有文章的分类 | 400 |
| 5 | 转移分类后再删 | 成功 |
| 6 | 删除标签后 | `tag_articles` 无残留 |
| 7 | 前台列表 | 只返回 `status=1` |
| 8 | count 接口 | 只统计启用的 |
| 9 | 表名 | 查询走 `categorys`（少个 e） |

---

## 9. 开放问题

1. **名称唯一性靠代码保证，没有唯一索引**：并发创建同名分类会插两条。
   建议加 `UNIQUE(category_name)`。这需要你拍板（与 likes 唯一索引同类问题）。
2. **分类只有一级**：未来要不要支持二级分类？当前 ER 不支持，要加 `parent_id`。
   建议不做，够用。
3. **`status=0` 的分类下还能有文章吗**：能。禁用只影响前台列表展示，不影响已有文章。
   这是现状，是否需要禁用时连带隐藏文章？建议不做。
