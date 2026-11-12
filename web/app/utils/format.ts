/**
 * 时间格式化。
 *
 * ⚠️ 后端返回的时间形如 `2026-11-01T10:00:00Z`，但**这个 Z 是硬贴上去的**：
 * 数据库里存的是东八区本地时间，序列化时直接拼了个字面量 Z。
 *
 * 如果直接 `new Date("2026-11-01T10:00:00Z")`，浏览器会按 UTC 解析，
 * 再转成本地时区，结果**多出 8 小时**，23 点后的文章会显示成第二天。
 *
 * 所以这里先去掉 Z 再解析，按本地时间处理。
 */

/** 把后端的伪 UTC 字符串转成 Date（按本地时间理解）。 */
export function parseApiTime(value: string | null | undefined): Date | null {
  if (!value) return null
  // 去掉结尾的 Z，让 Date 按本地时区解析
  const normalized = value.replace(/Z$/, '')
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
