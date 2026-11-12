/**
 * 后台路由守卫：必须是管理员。
 *
 * 只在客户端判断（token 在 localStorage）。普通用户访问后台直接回首页，
 * 不提示「无权限」—— 他本来就不该知道这个地址存在。
 *
 * 真正的权限校验在后端（`require_admin` 依赖），这里只负责跳转。
 */
export default defineNuxtRouteMiddleware((to) => {
  if (import.meta.server) return

  const { isLoggedIn, isAdmin } = useAuth()

  if (!isLoggedIn.value) {
    return navigateTo({ path: '/login', query: { redirect: to.fullPath } })
  }
  if (!isAdmin.value) {
    return navigateTo('/')
  }
})
