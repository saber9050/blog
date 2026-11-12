import type { ApiResponse } from '~/types/api'

/**
 * 后端接口调用封装。
 *
 * 解决三件重复的事：
 *
 * 1. **地址分离**：浏览器走相对路径（同源，由 Nginx / devProxy 转发），
 *    服务端渲染时没有同源概念，必须直连后端。两边地址从 runtimeConfig 取。
 * 2. **解包**：后端统一返回 `{code, message, data}`，调用方只想要 `data`。
 * 3. **错误**：`code !== 0` 时抛 `createError`，让 Nuxt 的错误页和
 *    `useAsyncData` 的 error 状态正常工作，而不是把错误码当正常数据往下传。
 */
export function useApi() {
  const config = useRuntimeConfig()
  // SSR 阶段没有「同源」概念，必须直连后端；浏览器端走相对路径
  const baseURL = import.meta.server ? config.apiBaseServer : config.public.apiBase

  /**
   * 发一次请求并解包。
   *
   * @param path 相对 `/api/v1` 的路径，如 `/articles`
   * @param options $fetch 的选项，可传 query / method / body / headers
   * @returns 解包后的业务数据
   * @throws createError 当 code !== 0 或网络异常
   */
  async function request<T>(path: string, options: Record<string, unknown> = {}): Promise<T> {
    let res: ApiResponse<T>

    try {
      res = await $fetch<ApiResponse<T>>(path, { baseURL, ...options })
    } catch (err: unknown) {
      // 网络层错误（后端没起、超时）或非 2xx：统一转成 503，避免把
      // fetch 的原始堆栈暴露到页面上
      throw createError({
        statusCode: 503,
        statusMessage: '服务暂时不可用',
        data: { cause: String(err) }
      })
    }

    if (res.code !== 0) {
      throw createError({
        statusCode: res.code >= 400 ? res.code : 400,
        statusMessage: res.message
      })
    }

    // data 缺失（后端约定：为空时不输出该字段）统一按 null 返回
    return (res.data ?? null) as T
  }

  return { request }
}
