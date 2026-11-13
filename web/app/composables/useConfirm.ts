/**
 * 全局确认框。
 *
 * 为什么不直接用 `window.confirm`：
 * 那个是浏览器的原生对话框，字体、配色、按钮位置全由系统决定，
 * 和本站「暖白纸面 + 近黑强调色」的风格完全不搭，而且移动端还会显示域名，
 * 看着像钓鱼弹窗。
 *
 * 用法：
 *
 *     const { confirm } = useConfirm()
 *     if (!await confirm({ title: '删除这篇文章？', danger: true })) return
 *
 * 渲染由 `components/ConfirmDialog.vue` 负责，它挂在 `app.vue` 里，
 * 全站只需要一个实例 —— 同一时刻也只可能有一个确认框。
 */

export interface ConfirmOptions {
  /** 标题，一句话说清要确认什么 */
  title: string
  /** 补充说明：后果、范围、能不能恢复 */
  description?: string
  /** 确认按钮文字，默认「确定」。动词化更好，如「删除」 */
  confirmText?: string
  /** 取消按钮文字，默认「取消」 */
  cancelText?: string
  /** 危险操作：确认按钮变玫红。删除类操作一律传 true */
  danger?: boolean
}

/**
 * 模块级单例状态。
 *
 * 用 `reactive` 而不是 `useState`：`useState` 要求值可序列化（要进 payload），
 * 而这里还有个 Promise 的 resolver 无法序列化。确认框本来就只在客户端出现，
 * 不需要跨服务端 / 客户端同步。
 */
const state = reactive<ConfirmOptions & { open: boolean }>({
  open: false,
  title: '',
  description: '',
  confirmText: '',
  cancelText: '',
  danger: false
})

/** 当前等待结果的 Promise resolver；null 表示没有待确认的请求 */
let pending: ((ok: boolean) => void) | null = null

export function useConfirm() {
  /**
   * 打开确认框并等待用户选择。
   *
   * @param options 文案配置；只传字符串时按标题处理
   * @returns 用户点了确认返回 true，取消 / 关闭返回 false
   */
  function confirm(options: ConfirmOptions | string): Promise<boolean> {
    // 上一个还没关就又弹一个：按「取消」结算，避免旧 Promise 永远挂着
    pending?.(false)

    Object.assign(
      state,
      typeof options === 'string' ? { title: options } : options,
      { open: true }
    )

    return new Promise<boolean>((resolve) => {
      pending = resolve
    })
  }

  /** 关闭并结算结果。只由 ConfirmDialog 调用。 */
  function settle(ok: boolean): void {
    state.open = false
    pending?.(ok)
    pending = null
  }

  return { state, confirm, settle }
}
