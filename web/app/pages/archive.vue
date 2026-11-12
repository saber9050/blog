<script setup lang="ts">
import type { Article, PageResult } from '~/types/api'

/**
 * 归档页：按年月分组列出全部文章。
 *
 * 一次拉 100 篇（后端上限），不做分页 —— 归档页的用途是「一眼看全」，
 * 翻页反而破坏这个用途。超过 100 篇再考虑按年份分页。
 */
const api = useApi()

const { data, error } = await useAsyncData('archive', () =>
  api.request<PageResult<Article>>('/articles', { query: { page: 1, page_size: 100 } })
)

const articles = computed(() => data.value?.list ?? [])

/** 按「年 → 月」两级分组，组内保持后端给的倒序。 */
const grouped = computed(() => {
  const years = new Map<number, Map<number, Article[]>>()

  for (const item of articles.value) {
    const date = parseApiTime(item.created_at)
    if (!date) continue
    const y = date.getFullYear()
    const m = date.getMonth() + 1

    if (!years.has(y)) years.set(y, new Map())
    const months = years.get(y)!
    if (!months.has(m)) months.set(m, [])
    months.get(m)!.push(item)
  }

  return [...years.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, months]) => ({
      year,
      months: [...months.entries()]
        .sort((a, b) => b[0] - a[0])
        .map(([month, list]) => ({ month, list }))
    }))
})

const total = computed(() => data.value?.total ?? 0)

useSeoMeta({
  title: '归档',
  description: '全部文章，按时间排列。'
})
</script>

<template>
  <div>
    <header class="mb-14">
      <h1 class="font-serif text-[2rem] leading-tight font-semibold text-stone-900 dark:text-stone-100">
        归档
      </h1>
      <p class="mt-3 text-sm text-stone-400 dark:text-stone-500">
        共 {{ total }} 篇
      </p>
    </header>

    <div
      v-if="error"
      class="text-sm text-stone-400"
    >
      暂时取不到文章列表。
    </div>

    <div
      v-else-if="grouped.length === 0"
      class="text-sm text-stone-400"
    >
      还没有文章。
    </div>

    <div
      v-else
      class="space-y-14"
    >
      <section
        v-for="group in grouped"
        :key="group.year"
      >
        <h2 class="font-serif text-3xl font-semibold text-stone-400/80 dark:text-stone-600">
          {{ group.year }}
        </h2>

        <div
          v-for="item in group.months"
          :key="item.month"
          class="mt-6"
        >
          <h3 class="text-xs tracking-widest text-stone-400 uppercase dark:text-stone-500">
            {{ item.month }} 月
          </h3>

          <ul class="mt-3 space-y-3">
            <li
              v-for="article in item.list"
              :key="article.id"
            >
              <NuxtLink
                :to="`/articles/${article.id}`"
                class="group flex items-baseline justify-between gap-4"
              >
                <span
                  class="text-[0.95rem] text-stone-700 transition-colors group-hover:text-stone-900
                         dark:text-stone-300 dark:group-hover:text-stone-100"
                >
                  {{ article.title }}
                </span>
                <span class="shrink-0 font-mono text-xs text-stone-300 dark:text-stone-600">
                  {{ formatDateShort(article.created_at).slice(5) }}
                </span>
              </NuxtLink>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </div>
</template>
