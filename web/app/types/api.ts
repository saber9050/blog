/**
 * 后端接口的类型定义。
 *
 * 与 docs 下各模块的 api.md 一一对应。改后端契约时这里必须同步改，
 * 否则 TypeScript 检查能过、运行时字段却对不上，是最难查的一类 bug。
 */

/** 统一响应包裹。`data` 为空时后端不输出该字段。 */
export interface ApiResponse<T> {
  code: number
  message: string
  data?: T
}

/** 分页结果的公共结构。 */
export interface PageResult<T> {
  list: T[]
  total: number
  page: number
  page_size: number
}

/** 分类 / 标签的引用结构，出现在文章的嵌套字段里。 */
export interface TaxonomyRef {
  id: number
  name: string
}

/** 文章条目。列表、详情、后台列表共用。 */
export interface Article {
  id: number
  title: string
  summary: string
  cover_url: string
  status: number
  views: number
  like_count: number
  comment_count: number
  is_liked: boolean
  author_name: string
  category: TaxonomyRef | null
  tags: TaxonomyRef[]
  /** 形如 `2026-11-01T10:00:00Z`，注意这个 Z 不是 UTC，见 utils/format.ts */
  created_at: string
  /** 仅详情接口返回 */
  content?: string
}

/** 文章列表的查询参数。 */
export interface ArticleListQuery {
  page?: number
  page_size?: number
  sort?: 'latest' | 'popular'
  category_id?: number
  tag_ids?: string
  keyword?: string
}

/** 站点统计，首页顶部用。 */
export interface ArticleStats {
  article_count: number
  comment_count: number
  category_count: number
  tag_count: number
}

/** 分类 / 标签（前台列表用）。 */
export interface Taxonomy {
  id: number
  name: string
}

/** 关于页。字段名以 `docs/06-about/api.md` 为准，`git_hub` 是历史拼写。 */
export interface About {
  admin_name: string
  avatar_url: string
  email: string
  introduction: string
  tech_stack: string
  my_story: string
  why: string
  interest: string
  git_hub: string
  csdn: string
}
