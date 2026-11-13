<script setup lang="ts">
import type { PageResult } from '~/types/api'

/**
 * 后台评论管理。
 *
 * 列表只返回未删除的评论（后端已经过滤），所以这里不需要处理「已删除」占位 ——
 * 那是前台评论区的事。
 *
 * 时间格式是 `...Z`，与前台评论的 `+08:00` 不同，统一走 formatRelative
 * 里的 parseApiTime（它按结尾是否为 Z 分流）。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

interface AdminComment {
  id: number
  article_title: string
  user_name: string
  content: string
  created_at: string
}

const api = useApi()
const { confirm } = useConfirm()

const page = ref(1)
const pageSize = ref(20)
const articleTitle = ref('')
const userName = ref('')

const list = ref<AdminComment[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

const selected = ref<number[]>([])
const batchMode = ref(false)

const allChecked = computed({
  get: () => list.value.length > 0 && selected.value.length === list.value.length,
  set: (value: boolean) => {
    selected.value = value ? list.value.map(c => c.id) : []
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (articleTitle.value.trim()) query.article_title = articleTitle.value.trim()
    if (userName.value.trim()) query.user_name = userName.value.trim()

    const res = await api.request<PageResult<AdminComment>>('/admin/comments', { query })
    list.value = res.list
    total.value = res.total
    selected.value = []
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
}

function applyFilter() {
  page.value = 1
  load()
}

function goPage(next: number) {
  page.value = next
  load()
}

/** 改每页条数要回到第 1 页，否则可能落在空页上。 */
function onPageSize(size: number) {
  pageSize.value = size
  page.value = 1
  load()
}

function toggle(id: number) {
  const index = selected.value.indexOf(id)
  if (index >= 0) selected.value.splice(index, 1)
  else selected.value.push(id)
}

async function removeOne(comment: AdminComment) {
  const ok = await confirm({
    title: '删除这条评论？',
    description: `「${comment.user_name}」的评论及其下的回复会一起删除。`,
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
  try {
    await api.request(`/admin/comments/${comment.id}`, { method: 'DELETE' })
    if (list.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

async function removeSelected() {
  if (selected.value.length === 0) return
  const ok = await confirm({
    title: `删除选中的 ${selected.value.length} 条评论？`,
    description: '每条评论下的回复会一并删除，不可恢复。',
    confirmText: '删除',
    danger: true
  })
  if (!ok) return

  try {
    const res = await api.request<{ count: number }>('/admin/comments', {
      method: 'DELETE',
      body: { ids: selected.value }
    })
    // 删完可能整页空掉，回退一页
    if (res.count >= list.value.length && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '批量删除失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-shell">
    <div class="flex shrink-0 items-center justify-between">
      <div>
        <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
          评论
        </h1>
      </div>

      <div class="flex items-center gap-3">
        <button
          v-if="batchMode && selected.length > 0"
          type="button"
          class="rounded-md border border-rose-200 px-3 py-1.5 text-xs text-rose-600
                 transition-colors hover:bg-rose-50 dark:border-rose-900 dark:text-rose-400
                 dark:hover:bg-rose-950"
          @click="removeSelected"
        >
          删除选中（{{ selected.length }}）
        </button>
        <button
          type="button"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
                 transition-colors hover:border-stone-400 hover:text-stone-900
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
          @click="batchMode = !batchMode; selected = []"
        >
          {{ batchMode ? '退出批量' : '批量操作' }}
        </button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="mt-6 flex shrink-0 flex-wrap items-center gap-3">
      <input
        v-model="articleTitle"
        type="text"
        placeholder="文章标题"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
               dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
               dark:focus:border-stone-600"
        @keyup.enter="applyFilter"
      >
      <input
        v-model="userName"
        type="text"
        placeholder="评论者昵称"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
               dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
               dark:focus:border-stone-600"
        @keyup.enter="applyFilter"
      >
      <button
        type="button"
        class="shrink-0 rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
               transition-colors hover:border-stone-400 hover:text-stone-900
               dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        @click="applyFilter"
      >
        筛选
      </button>
    </div>

    <p
      v-if="error"
      class="mt-3 shrink-0 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <!-- 列表：滚动条在这一层，表头吸顶 -->
    <div class="admin-scroll mt-6 rounded-lg border border-stone-200 dark:border-stone-800">
      <table class="w-full text-left text-xs">
        <thead class="text-stone-500 dark:text-stone-400">
          <tr>
            <th
              v-if="batchMode"
              class="w-10 px-4 py-2.5"
            >
              <input
                v-model="allChecked"
                type="checkbox"
                class="size-3.5 accent-stone-900"
              >
            </th>
            <th class="px-4 py-2.5 font-medium">
              评论内容
            </th>
            <th class="w-40 px-4 py-2.5 font-medium">
              所属文章
            </th>
            <th class="w-24 px-4 py-2.5 font-medium">
              评论者
            </th>
            <th class="w-24 px-4 py-2.5 font-medium">
              时间
            </th>
            <th class="w-16 px-4 py-2.5 font-medium">
              操作
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100 dark:divide-stone-800">
          <tr v-if="loading">
            <td
              :colspan="batchMode ? 6 : 5"
              class="px-4 py-10 text-center text-stone-400"
            >
              加载中…
            </td>
          </tr>
          <tr v-else-if="list.length === 0">
            <td
              :colspan="batchMode ? 6 : 5"
              class="px-4 py-10 text-center text-stone-400"
            >
              没有匹配的评论
            </td>
          </tr>
          <tr
            v-for="comment in list"
            v-else
            :key="comment.id"
          >
            <td
              v-if="batchMode"
              class="px-4 py-2.5"
            >
              <input
                type="checkbox"
                class="size-3.5 accent-stone-900"
                :checked="selected.includes(comment.id)"
                @change="toggle(comment.id)"
              >
            </td>
            <td class="px-4 py-2.5">
              <p class="line-clamp-2 text-stone-700 dark:text-stone-300">
                {{ comment.content }}
              </p>
            </td>
            <td class="px-4 py-2.5">
              <span class="line-clamp-2 text-stone-500 dark:text-stone-400">
                {{ comment.article_title || '—' }}
              </span>
            </td>
            <td class="px-4 py-2.5 text-stone-500 dark:text-stone-400">
              {{ comment.user_name }}
            </td>
            <td class="px-4 py-2.5 text-stone-400 dark:text-stone-500">
              {{ formatDateShort(comment.created_at) }}
            </td>
            <td class="px-4 py-2.5">
              <button
                type="button"
                class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                @click="removeOne(comment)"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页：后台评论接口单页上限 50，所以档位只到 50 -->
    <AdminPager
      class="mt-4"
      :page="page"
      :total="total"
      :page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      @update:page="goPage"
      @update:page-size="onPageSize"
    />
  </div>
</template>
