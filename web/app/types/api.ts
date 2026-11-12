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

/** 后台分类 / 标签条目，比前台多状态与创建时间。 */
export interface AdminTaxonomy {
  id: number
  name: string
  status: number
  created_at: string
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

/**
 * 邮箱验证码的用途。四个值互不相通：不同 purpose 各存一个 Redis key，
 * 但**发送频率限制跨 purpose 共享**（同一邮箱 60 秒只能发一次）。
 */
export type CaptchaPurpose = 'login' | 'reset_password' | 'reset_email' | 'add_email'

/** 邮箱验证码登录请求体。 */
export interface EmailLoginPayload {
  email: string
  purpose: 'login'
  captcha: string
}

/** 发送邮箱验证码。 */
export interface SendCaptchaPayload {
  email: string
  purpose: CaptchaPurpose
}

/** 用邮箱验证码重置密码。 */
export interface ResetPasswordPayload {
  email: string
  captcha: string
  new_password: string
  ack: string
}

// ---------------------------------------------------------------
// 用户模块
// ---------------------------------------------------------------

/**
 * 当前用户资料。
 *
 * ⚠️ `staus`（应为 status）和 `create_at`（应为 created_at）是后端的历史拼写，
 * 必须照抄 —— 改名等于线上白屏。`user_id` 也不是 `id`。
 */
export interface UserProfile {
  user_id: number
  user_name: string
  account: string
  email: string
  avatar_url: string
  introduction: string
  role_id: number
  staus: number
  create_at: string
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

// ---------------------------------------------------------------
// 评论模块
// ---------------------------------------------------------------

/**
 * 评论。
 *
 * 时间格式与其他模块不同：这里是 `2026-11-09T21:39:04.123456+08:00`（带时区偏移），
 * 不是文章那种假的 `Z`。所以可以直接 `new Date()` 解析。
 */
export interface Comment {
  id: number
  content: string
  user_id: number
  user_name: string
  avatar_url: string
  parent_id: number | null
  /** 回复目标昵称的快照，被回复的人改名后这里不变 */
  reply_to_name: string
  is_deleted: boolean
  created_at: string
  /** 仅一级评论有意义；二级恒为 0 */
  children_total: number
}

/** 发表评论的请求体。 */
export interface CreateCommentPayload {
  content: string
  parent_id?: number
  reply_to_name?: string
}
