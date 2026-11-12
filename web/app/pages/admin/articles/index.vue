<script setup lang="ts">
import type { Article, PageResult, Taxonomy } from '~/types/api'

/**
 * 后台文章列表。
 *
 * 筛选参数与前台不同：后台按 `tag_id`（单个），前台按 `tag_ids`（逗号分隔）。
 * 这里只做状态与关键字筛选，标签筛选留到需要时再加 —— 后台文章量不会大到
 * 必须靠标签定位。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

const api = useApi()

const page = ref(1)
/** 每页条数由分页条控制，改档位时回到第 1 页（见 onPageSize） */
const pageSize = ref(10)
const status = ref<'' | 0 | 1>('')
const keyword = ref('')
const categoryId = ref<number | ''>('')

const articles = ref<Article[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

const categories = ref<Taxonomy[]>([])

async function loadCategories() {
  try {
    categories.value = await api.request<Taxonomy[]>('/categories')
  } catch {
    categories.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (status.value !== '') query.status = status.value
    if (keyword.value.trim()) query.keyword = keyword.value.trim()
    if (categoryId.value !== '') query.category_id = categoryId.value

    const res = await api.request<PageResult<Article>>('/admin/articles', { query })
    articles.value = res.list
    total.value = res.total
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 任一筛选条件变化都回到第一页，否则会停在超出范围的页码上。 */
function applyFilter() {
  page.value = 1
  load()
}

function goPage(next: number) {
  page.value = next
  load()
}

/**
 * 改每页条数：页码必须归 1。
 * 比如原来 5 条/页停在第 4 页，改成 100 条/页后总页数只剩 1，
 * 不归 1 就会显示空列表。
 */
function onPageSize(size: number) {
  pageSize.value = size
  page.value = 1
  load()
}

async function remove(article: Article) {
  if (!confirm(`确定删除《${article.title}》？删除后评论与图片一并清理。`)) return
  try {
    await api.request(`/admin/articles/${article.id}`, { method: 'DELETE' })
    // 删完当前页最后一条时回退一页，避免停在空页
    if (articles.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

onMounted(() => {
  loadCategories()
  load()
})
</script>

<template>
  <div class="admin-shell">
    <div class="flex shrink-0 items-center justify-between">
      <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
        文章
      </h1>
      <NuxtLink
        to="/admin/articles/new"
        class="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
               transition-opacity hover:opacity-90 dark:bg-stone-100 dark:text-stone-900"
      >
        写文章
      </NuxtLink>
    </div>

    <!-- 筛选 -->
    <div class="mt-6 flex shrink-0 flex-wrap items-center gap-3">
      <input
        v-model="keyword"
        type="text"
        placeholder="搜索标题或摘要"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
               dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
               dark:focus:border-stone-600"
        @keyup.enter="applyFilter"
      >

      <select
        v-model="status"
        class="rounded-md border border-stone-200 bg-transparent px-3 py-1.5 text-xs
               text-stone-600 outline-none dark:border-stone-800 dark:text-stone-400"
        @change="applyFilter"
      >
        <option value="">
          全部状态
        </option>
        <option :value="1">
          已发布
        </option>
        <option :value="0">
          草稿
        </option>
      </select>

      <select
        v-model="categoryId"
        class="rounded-md border border-stone-200 bg-transparent px-3 py-1.5 text-xs
               text-stone-600 outline-none dark:border-stone-800 dark:text-stone-400"
        @change="applyFilter"
      >
        <option value="">
          全部分类
        </option>
        <option
          v-for="cat in categories"
          :key="cat.id"
          :value="cat.id"
        >
          {{ cat.name }}
        </option>
      </select>

      <button
        type="button"
        class="rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
               transition-colors hover:border-stone-400 hover:text-stone-900
               dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        @click="applyFilter"
      >
        筛选
      </button>
    </div>

    <p
      v-if="error"
      class="mt-4 shrink-0 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <!-- 表格：滚动条在这一层，表头吸顶（见 main.css 的 .admin-scroll） -->
    <div class="admin-scroll mt-6 rounded-lg border border-stone-200 dark:border-stone-800">
      <table class="w-full text-left text-xs">
        <thead class="text-stone-500 dark:text-stone-400">
          <tr>
            <th class="px-4 py-3 font-medium">
              标题
            </th>
            <th class="w-24 px-4 py-3 font-medium">
              状态
            </th>
            <th class="w-24 px-4 py-3 font-medium">
              分类
            </th>
            <th class="w-40 px-4 py-3 font-medium">
              数据
            </th>
            <th class="w-24 px-4 py-3 font-medium">
              更新
            </th>
            <th class="w-28 px-4 py-3 font-medium">
              操作
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100 dark:divide-stone-800">
          <tr v-if="loading">
            <td
              colspan="6"
              class="px-4 py-12 text-center text-stone-400"
            >
              加载中…
            </td>
          </tr>
          <tr v-else-if="articles.length === 0">
            <td
              colspan="6"
              class="px-4 py-12 text-center text-stone-400"
            >
              没有匹配的文章
            </td>
          </tr>
          <tr
            v-for="item in articles"
            v-else
            :key="item.id"
            class="transition-colors hover:bg-stone-50/60 dark:hover:bg-stone-900/40"
          >
            <td class="px-4 py-3">
              <NuxtLink
                :to="`/admin/articles/${item.id}`"
                class="text-stone-800 transition-colors hover:text-stone-500 dark:text-stone-200"
              >
                {{ item.title }}
              </NuxtLink>
              <p class="mt-0.5 line-clamp-1 text-[11px] text-stone-400 dark:text-stone-600">
                {{ item.summary || '—' }}
              </p>
            </td>
            <td class="px-4 py-3">
              <span
                class="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]"
                :class="item.status === 1
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                  : 'bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400'"
              >
                {{ item.status === 1 ? '已发布' : '草稿' }}
              </span>
            </td>
            <td class="px-4 py-3 text-stone-500 dark:text-stone-400">
              {{ item.category?.name ?? '—' }}
            </td>
            <td class="whitespace-nowrap px-4 py-3 text-stone-400 dark:text-stone-500">
              {{ item.views }} 阅 / {{ item.like_count }} 赞 / {{ item.comment_count }} 评
            </td>
            <td class="px-4 py-3 text-stone-400 dark:text-stone-500">
              {{ formatDateShort(item.created_at) }}
            </td>
            <td class="px-4 py-3">
              <div class="flex items-center gap-3">
                <NuxtLink
                  :to="`/admin/articles/${item.id}`"
                  class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                >
                  编辑
                </NuxtLink>
                <button
                  type="button"
                  class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                  @click="remove(item)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <AdminPager
      class="mt-4"
      :page="page"
      :total="total"
      :page-size="pageSize"
      @update:page="goPage"
      @update:page-size="onPageSize"
    />
  </div>
</template>
