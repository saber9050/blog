import type { EmailLoginPayload, LoginPayload, LoginResult } from '~/types/api'

/**
 * 登录状态。
 *
 * token 与用户信息存在 localStorage，所以**服务端渲染阶段拿不到** ——
 * SSR 时一律按未登录渲染，客户端 hydration 后立刻纠正。
 *
 * 代价是已登录用户打开页面时，导航栏会有一瞬间显示「登录」。
 * 换取的是不用把 JWT 塞进 cookie（cookie 更容易被 CSRF 利用）。
 */
export function useAuth() {
  const api = useApi()

  // useState 让 SSR 与 CSR 共享同一份状态，避免 hydration 时两套数据打架
  const user = useState<AuthUser | null>('auth-user', () => null)
  const token = useState<string | null>('auth-token', () => null)

  // 客户端首次进入：从 localStorage 恢复会话
  if (import.meta.client && !token.value) {
    const stored = getToken()
    if (stored) {
      token.value = stored
      user.value = readUser()
    }
  }

  const isLoggedIn = computed(() => Boolean(token.value && user.value))
  const isAdmin = computed(() => user.value?.roleId === 1)

  /** 把接口返回的登录结果落到本地与内存状态。 */
  function applyLogin(res: LoginResult): AuthUser {
    const next: AuthUser = {
      id: res.user_id,
      name: res.user_name,
      roleId: res.user_role_id
    }
    saveSession(res.access_token, next)
    token.value = res.access_token
    user.value = next
    return next
  }

  /** 账号密码登录（需要图形验证码）。 */
  async function login(payload: LoginPayload): Promise<AuthUser> {
    const res = await api.request<LoginResult>('/auth/login', {
      method: 'POST',
      body: payload
    })
    return applyLogin(res)
  }

  /** 邮箱验证码登录。 */
  async function loginByEmail(payload: EmailLoginPayload): Promise<AuthUser> {
    const res = await api.request<LoginResult>('/auth/email_login', {
      method: 'POST',
      body: payload
    })
    return applyLogin(res)
  }

  /**
   * 登出。
   *
   * 后端是幂等的（token 无效也返回成功），但网络异常时不能把用户卡在
   * 「点了登出却没反应」的状态，所以无论成败都清本地。
   */
  async function logout(): Promise<void> {
    try {
      await api.request('/auth/logout', { method: 'POST' })
    } catch {
      // 忽略：本地状态必须清掉
    } finally {
      clearSession()
      token.value = null
      user.value = null
    }
  }

  return { user, token, isLoggedIn, isAdmin, login, loginByEmail, logout }
}
