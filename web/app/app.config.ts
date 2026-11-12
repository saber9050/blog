/**
 * Nuxt UI 主题。
 *
 * primary 取 stone（近黑）而不是某个彩色：全站只有一个强调色，
 * 按钮、链接、选中态统一是深灰，视觉上更接近出版物而不是后台系统。
 * 换强调色只改这一行，所有组件跟着走。
 */
export default defineAppConfig({
  ui: {
    colors: {
      primary: 'stone',
      neutral: 'stone'
    }
  }
})
