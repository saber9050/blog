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
      // 刷新失败 = 会话彻底失效，清掉本地状态，让页面回到未登录
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
 * 3. **401 自动刷新并重放**：刷新失败才真正报错。
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

    let res: ApiResponse<T>

    try {
      res = await $fetch<ApiResponse<T>>(path, { baseURL, ...options, headers })
    } catch (err: unknown) {
      const error = err as { status?: number, statusCode?: number, data?: { message?: string } }
      const status = error.status ?? error.statusCode

      // 401 且不是刷新接口本身 → 刷新一次再重放
      if (status === 401 && !retry && !path.startsWith('/auth/refresh')) {
        const newToken = await refreshAccessToken(baseURL)
        if (newToken) {
          return request<T>(path, options, true)
        }
      }

      throw createError({
        statusCode: status && status >= 400 ? status : 503,
        statusMessage: error.data?.message ?? (status && status < 500 ? '请求失败' : '服务暂时不可用')
      })
    }

    if (res.code !== 0) {
      throw createError({
        statusCode: res.code >= 400 ? res.code : 400,
        statusMessage: res.message
      })
    }

    return (res.data ?? null) as T
  }

  return { request }
}
