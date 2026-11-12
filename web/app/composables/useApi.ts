import type { ApiResponse } from '~/types/api'

/** 登录用户的会话信息，存在 localStorage 与服务端渲染时的内存状态里。 */
export interface AuthUser {
  id: number
  name: string
  /** 1 = 管理员，0 = 普通用户 */
  roleId: number
}

const TOKEN_KEY = 'access_token'
const USER_KEY = 'auth_user'

/**
 * 业务码：access token 已过期。
 *
 * **不能只看 HTTP 401**。后端把 1xxx 段错误码统一映射成 HTTP 400
 * （见 `app/core/errors.py` 的 `BizError.http_status`，与 Go 版一致，
 * `docs/00-foundation/design.md` 的错误码表里 1006 → 400 也是这么写的）。
 * 也就是说 token 过期时拿到的是 `400 + {"code":1006,"message":"令牌已过期"}`，
 * 只有「没带 token」「token 无效」才是 401。
 *
 * 之前只判 401，导致最常见的「access 过期、refresh 还有效」这一路
 * 完全走不到刷新分支，用户会莫名其妙被要求重新登录。
 */
const TOKEN_EXPIRED_CODE = 1006

/**
 * 模块级刷新锁。
 *
 * 后端刷新会**轮换 tid**：新的 access token 一签发，旧的立即失效。
 * 所以两个并发请求同时 401 时，如果各自去刷新，后一个必然拿着已经作废的
 * token 去刷，结果就是「刷新失败 → 被踢下线」。
 *
 * 这里用模块级 Promise 做 single-flight：同一时刻只有一个刷新在飞，
 * 其余请求等它的结果。
 */
let refreshing: Promise<string | null> | null = null

/**
 * 判断这次失败是否属于「该刷新 token 了」。
 *
 * @param status HTTP 状态码
 * @param body 响应体（可能是统一响应结构，也可能是纯文本）
 */
function shouldRefresh(status?: number, body?: unknown): boolean {
  if (status === 401) return true
  const code = (body as { code?: number } | null | undefined)?.code
  return code === TOKEN_EXPIRED_CODE
}

/** 从 localStorage 取当前 token（服务端渲染时没有 localStorage）。 */
export function getToken(): string | null {
  if (!import.meta.client) return null
  return localStorage.getItem(TOKEN_KEY)
}

/** 写入本地会话。 */
export function saveSession(token: string, user: AuthUser): void {
  if (!import.meta.client) return
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

/** 清除本地会话。 */
export function clearSession(): void {
  if (!import.meta.client) return
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

/** 读取本地缓存的用户信息，用于刷新页面后恢复登录态。 */
export function readUser(): AuthUser | null {
  if (!import.meta.client) return null
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    // 存的内容坏了就当没登录，不要让页面崩在 JSON.parse 上
    return null
  }
}

/**
 * 执行一次刷新。并发调用会复用同一个 Promise。
 *
 * @param baseURL 后端地址
 * @returns 新的 access token；刷新失败返回 null
 */
export async function refreshAccessToken(baseURL: string): Promise<string | null> {
  if (refreshing) return refreshing

  const current = getToken()
  if (!current) return null

  refreshing = (async () => {
    try {
      const res = await $fetch<ApiResponse<{ access_token: string }>>('/auth/refresh', {
        baseURL,
        method: 'POST',
        headers: { Authorization: `Bearer ${current}` }
      })
      const token = res.data?.access_token
      if (!token) return null

      // 刷新只换 token，用户信息不变；用 localStorage 直写避免依赖 AuthUser 结构
      localStorage.setItem(TOKEN_KEY, token)
      return token
    } catch {
      /**
       * 刷新失败不一定是会话真的没了：并发场景下别的请求可能已经刷新成功，
       * 把 localStorage 里的 token 换掉了。此时本地 token 已不是发起时那个，
       * 说明会话还在 —— 直接用它，千万别 clearSession 把用户踢下线。
       */
      const latest = getToken()
      if (latest && latest !== current) return latest

      // 才是真失效：清掉本地状态，让页面回到未登录
      clearSession()
      return null
    } finally {
      // 无论成败都要释放锁，否则后续请求会永远等在这里
      refreshing = null
    }
  })()

  return refreshing
}

/**
 * 后端接口调用封装。
 *
 * 相比裸 `$fetch`，它处理四件事：
 *
 * 1. **地址分离**：浏览器走相对路径（同源，由 Nginx / devProxy 转发），
 *    服务端渲染时没有同源概念，必须直连后端。
 * 2. **自动带 token**：有会话就注入 `Authorization`，调用方不用管。
 * 3. **token 过期自动刷新并重放**：判据是「HTTP 401」或「业务码 1006」
 *    （后端把过期映射成 400 + 1006），刷新仍失败才真正报错。
 * 4. **解包与错误**：把 `{code, message, data}` 拆开，非 0 抛 `createError`。
 */
export function useApi() {
  const config = useRuntimeConfig()
  const baseURL = import.meta.server ? config.apiBaseServer : config.public.apiBase

  /**
   * 发一次请求并解包。
   *
   * @param path 相对 `/api/v1` 的路径，如 `/articles`
   * @param options `$fetch` 的选项
   * @param retry 内部用：标记这次是否为刷新后的重放，防止无限循环
   */
  async function request<T>(
    path: string,
    options: Record<string, unknown> = {},
    retry = false
  ): Promise<T> {
    const token = getToken()
    const headers: Record<string, string> = {
      ...((options.headers as Record<string, string>) ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }

    /**
     * 刷新后重放一次；刷新失败就不再重试，避免死循环。
     *
     * 返回值刻意包一层 `replayed` 标记而不是「`null` 表示没重放」：
     * 接口的 `data` 本身可能就是 `null`（如 DELETE / logout），
     * 用 null 当哨兵会把成功的重放误判成失败。
     */
    async function replayWithFreshToken(): Promise<{ replayed: true, value: T } | { replayed: false }> {
      if (retry || path.startsWith('/auth/refresh')) return { replayed: false }
      const newToken = await refreshAccessToken(baseURL)
      if (!newToken) return { replayed: false }
      return { replayed: true, value: await request<T>(path, options, true) }
    }

    let res: ApiResponse<T>

    try {
      res = await $fetch<ApiResponse<T>>(path, { baseURL, ...options, headers })
    } catch (err: unknown) {
      const error = err as {
        status?: number
        statusCode?: number
        data?: { code?: number, message?: string }
      }
      const status = error.status ?? error.statusCode

      /**
       * token 过期（400 + code 1006）与 401 都要走刷新。
       *
       * `token` 是本次请求发出去时带的那个：为空说明是「未登录」而非「过期」，
       * 这种情况刷新没有意义（没有凭证可换），直接把后端的原文抛出去，
       * 别把游客/未登录场景也标成「登录已过期」。
       */
      if (token && shouldRefresh(status, error.data)) {
        const replayed = await replayWithFreshToken()
        if (replayed.replayed) return replayed.value

        // 走到这里说明刷新也失败了：会话真的没了，给一句能指导操作的提示
        throw createError({
          statusCode: 401,
          statusMessage: '登录已过期，请重新登录'
        })
      }

      throw createError({
        statusCode: status && status >= 400 ? status : 503,
        statusMessage: error.data?.message ?? (status && status < 500 ? '请求失败' : '服务暂时不可用')
      })
    }

    if (res.code !== 0) {
      // 兜底：万一后端某个接口用 200 包了 1006，也要能刷新
      if (token && res.code === TOKEN_EXPIRED_CODE) {
        const replayed = await replayWithFreshToken()
        if (replayed.replayed) return replayed.value
        throw createError({ statusCode: 401, statusMessage: '登录已过期，请重新登录' })
      }

      throw createError({
        statusCode: res.code >= 400 ? res.code : 400,
        statusMessage: res.message
      })
    }

    return (res.data ?? null) as T
  }

  return { request }
}
