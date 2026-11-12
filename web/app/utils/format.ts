/**
 * 把后端时间字符串转成 Date。
 *
 * 后端有两种格式，必须分开处理：
 *
 * 1. 文章类：`2026-11-01T10:00:00Z` —— 这个 Z 是**字面量**，库里存的是东八区
 *    本地时间。直接 new Date 会按 UTC 解析，凭空多出 8 小时。
 * 2. 评论类：`2026-11-09T21:39:04.123456+08:00` —— 带真实时区偏移，可以直接解析。
 *
 * 判断依据是结尾有没有 `Z`：带偏移量的串不会以 Z 结尾。
 */
export function parseApiTime(value: string | null | undefined): Date | null {
  if (!value) return null
  const normalized = value.endsWith('Z') ? value.replace(/Z$/, '') : value
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

/** 相对时间：刚刚 / 3 小时前 / 2 天前 / 具体日期。 */
export function formatRelative(value: string | null | undefined): string {
  const date = parseApiTime(value)
  if (!date) return ''

  const diff = Date.now() - date.getTime()
  const minute = 60 * 1000
  const hour = 60 * minute
  const day = 24 * hour

  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`

  return formatDate(value)
}

/** 日期：2026 年 11 月 1 日。 */
export function formatDate(value: string | null | undefined): string {
  const date = parseApiTime(value)
  if (!date) return ''
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

/** 紧凑日期：2026.11.01，列表右侧用。 */
export function formatDateShort(value: string | null | undefined): string {
  const date = parseApiTime(value)
  if (!date) return ''
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}.${m}.${d}`
}

/** 阅读时长估算：中文按每分钟 400 字，最少 1 分钟。 */
export function readingTime(content: string | null | undefined): string {
  if (!content) return ''
  // 去掉 markdown 符号和空白，只算正文
  const text = content.replace(/[#*`>\-()!]/g, '').replace(/\s+/g, '')
  const minutes = Math.max(1, Math.round(text.length / 400))
  return `${minutes} 分钟`
}
