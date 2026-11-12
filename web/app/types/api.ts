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

/** 图形验证码。字段名是 `base_64`（下划线），不是 `base64`。 */
export interface ImageCaptcha {
  captcha_id: string
  /** 完整的 data URI，可直接塞进 `<img src>` */
  base_64: string
}

/** 登录成功的结果。refresh token 藏在 access token 的 tid claim 里，不对外返回。 */
export interface LoginResult {
  user_name: string
  user_id: number
  /** 1 管理员 / 0 普通用户 */
  user_role_id: number
  access_token: string
}

/** 登录请求体。 */
export interface LoginPayload {
  account: string
  password: string
  captcha_key: string
  captcha_code: string
}

/** 注册请求体。 */
export interface RegisterPayload {
  user_name: string
  account: string
  password: string
  ack: string
}

/** 邮箱验证码登录请求体。 */
export interface EmailLoginPayload {
  email: string
  purpose: 'login' | 'reset'
  captcha: string
}

/** 发送邮箱验证码的用途。 */
export type CaptchaPurpose = 'login' | 'reset'

// ---------------------------------------------------------------
// 用户模块
// ---------------------------------------------------------------

/** 当前用户资料。注意 `staus` / `create_at` 是后端的历史拼写，不要改。 */
export interface UserProfile {
  user_name: string
  account: string
  avatar_url: string
  introduction: string
  email: string
  staus: number
  create_at: string
  role_id: number
}

/** 后台用户列表项。分页字段是 `pageSize`（驼峰），与其他模块不同。 */
export interface AdminUserItem {
  id: number
  user_name: string
  account: string
  avatar_url: string
  email: string
  status: number
  created_at: string
}

export interface AdminUserPage {
  list: AdminUserItem[]
  total: number
  page: number
  pageSize: number
}
