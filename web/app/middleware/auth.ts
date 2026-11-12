/**
 * 需要登录的页面路由守卫。
 *
 * ⚠️ 只在客户端校验：token 在 localStorage 里，服务端渲染时读不到，
 * 在服务端判断会把已登录用户也踢回登录页。
 *
 * 真正的权限校验在后端（401 / 403），这里只负责跳转体验。
 */
export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return

  const { isLoggedIn } = useAuth()
  if (!isLoggedIn.value) {
    // 带上来源，登录后跳回去
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }
})
