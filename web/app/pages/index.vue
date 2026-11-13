<script setup lang="ts">
import type { Article, PageResult } from '~/types/api'

/**
 * 首页：文章列表。
 *
 * 数据在服务端取好再吐 HTML —— 这是选 Nuxt 而不是纯 SPA 的核心原因：
 * 搜索引擎要能看到文章标题和摘要。
 */
const route = useRoute()
const api = useApi()

const page = computed(() => Number(route.query.page) || 1)
const PAGE_SIZE = 10

const { data, status, error } = await useAsyncData(
  () => `articles-${page.value}`,
  () => api.request<PageResult<Article>>('/articles', {
    query: { page: page.value, page_size: PAGE_SIZE }
  }),
  { watch: [page] }
)

const articles = computed(() => data.value?.list ?? [])
const total = computed(() => data.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

useSeoMeta({
  title: '文章',
  description: '记录后端、系统设计与日常思考。'
})
</script>

<template>
  <div>
    <!-- 顶部引言：只放一句，不堆砌 -->
    <section class="mb-16">
      <h1 class="font-serif text-[2rem] leading-tight font-semibold text-stone-900 sm:text-[2.5rem] dark:text-stone-100">
        写代码，也写为什么。
      </h1>
      <p class="mt-4 max-w-xl text-base leading-relaxed text-stone-500 dark:text-stone-400">
        这里记录后端开发、系统设计与一些没什么用但想说的话。
      </p>
    </section>

    <!-- 加载态：骨架屏比转圈更少跳动 -->
    <div
      v-if="status === 'pending'"
      class="space-y-12"
    >
      <div
        v-for="i in 3"
        :key="i"
        class="flex items-start gap-5 sm:gap-6"
      >
        <div class="min-w-0 flex-1 space-y-3">
          <USkeleton class="h-7 w-2/3" />
          <USkeleton class="h-4 w-full" />
          <USkeleton class="h-3 w-1/4" />
        </div>
        <USkeleton class="aspect-[4/3] w-20 shrink-0 rounded-md sm:w-40" />
      </div>
    </div>

    <!-- 错误态：后端没起时给一句人话，不吐堆栈 -->
    <div
      v-else-if="error"
      class="rounded-lg border border-stone-200 px-6 py-10 text-center dark:border-stone-800"
    >
      <UIcon
        name="i-lucide-cloud-off"
        class="mx-auto mb-3 size-6 text-stone-400"
      />
      <p class="text-sm text-stone-500 dark:text-stone-400">
        文章暂时取不到，稍后再试。
      </p>
    </div>

    <!-- 空态 -->
    <div
      v-else-if="articles.length === 0"
      class="rounded-lg border border-dashed border-stone-200 px-6 py-16 text-center dark:border-stone-800"
    >
      <p class="text-sm text-stone-400">
        还没有发布任何文章。
      </p>
    </div>

    <!-- 列表 -->
    <div v-else>
      <article
        v-for="(item, index) in articles"
        :key="item.id"
        class="group border-b border-stone-200 py-10 first:pt-0 last:border-0 dark:border-stone-800"
      >
        <NuxtLink
          :to="`/articles/${item.id}`"
          class="block"
        >
          <!-- 文字在左、封面缩略图在右：不打断「序号 + 标题」这条竖向轴 -->
          <div class="flex items-start gap-5 sm:gap-6">
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-3">
                <span class="font-mono text-xs text-stone-400 dark:text-stone-500">
                  {{ String(index + 1 + (page - 1) * PAGE_SIZE).padStart(2, '0') }}
                </span>
                <h2
                  class="font-serif text-xl leading-snug font-semibold text-stone-900 transition-colors
                         group-hover:text-stone-600 sm:text-2xl dark:text-stone-100 dark:group-hover:text-stone-300"
                >
                  {{ item.title }}
                </h2>
              </div>

              <p
                v-if="item.summary"
                class="mt-3 line-clamp-2 pl-7 text-[0.95rem] leading-relaxed text-stone-500 dark:text-stone-400"
              >
                {{ item.summary }}
              </p>

              <div class="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 pl-7 text-xs text-stone-400 dark:text-stone-500">
                <time>{{ formatDateShort(item.created_at) }}</time>
                <template v-if="item.category">
                  <span class="text-stone-300 dark:text-stone-700">/</span>
                  <span>{{ item.category.name }}</span>
                </template>
                <span class="text-stone-300 dark:text-stone-700">/</span>
                <span>{{ item.views }} 次阅读</span>
                <template v-if="item.comment_count > 0">
                  <span class="text-stone-300 dark:text-stone-700">/</span>
                  <span>{{ item.comment_count }} 条评论</span>
                </template>
              </div>
            </div>

            <!--
              封面：有才占位，没封面时文字直接用满宽度 —— 不做灰底占位框，
              一堆空框会把这张纸变成表格。
              固定 4:3 裁切（object-cover），不同尺寸的原图在列表里高度一致。
            -->
            <div
              v-if="item.cover_url"
              class="w-20 shrink-0 overflow-hidden rounded-md bg-stone-100 sm:w-40 dark:bg-stone-900"
            >
              <img
                :src="item.cover_url"
                :alt="item.title"
                loading="lazy"
                class="aspect-[4/3] w-full object-cover transition-transform duration-500 group-hover:scale-105"
              >
            </div>
          </div>
        </NuxtLink>
      </article>
    </div>

    <!-- 分页：只在超过一页时出现 -->
    <nav
      v-if="totalPages > 1"
      class="mt-12 flex items-center justify-between text-sm"
    >
      <NuxtLink
        v-if="page > 1"
        :to="{ query: { page: page - 1 } }"
        class="inline-flex items-center gap-1.5 text-stone-500 transition-colors hover:text-stone-900
               dark:text-stone-400 dark:hover:text-stone-100"
      >
        <UIcon
          name="i-lucide-arrow-left"
          class="size-4"
        />
        上一页
      </NuxtLink>
      <span v-else />

      <span class="text-xs text-stone-400 dark:text-stone-500">
        {{ page }} / {{ totalPages }}
      </span>

      <NuxtLink
        v-if="page < totalPages"
        :to="{ query: { page: page + 1 } }"
        class="inline-flex items-center gap-1.5 text-stone-500 transition-colors hover:text-stone-900
               dark:text-stone-400 dark:hover:text-stone-100"
      >
        下一页
        <UIcon
          name="i-lucide-arrow-right"
          class="size-4"
        />
      </NuxtLink>
      <span v-else />
    </nav>
  </div>
</template>
