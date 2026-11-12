<script setup lang="ts">
import { marked } from 'marked'
import type { Article } from '~/types/api'

/**
 * 文章详情。
 *
 * 正文是 Markdown，服务端直接渲染成 HTML 再输出 —— 这样爬虫和
 * 「查看源代码」都能看到全文，不是靠 JS 现场拼。
 *
 * 不做 HTML 过滤：正文只有作者（管理员）能写，属于可信内容。
 * 如果以后开放投稿，这里必须加 sanitize。
 */
const route = useRoute()
const api = useApi()

const articleId = computed(() => Number(route.params.article_id))

const { data: article, error } = await useAsyncData(
  () => `article-${articleId.value}`,
  () => api.request<Article>(`/articles/${articleId.value}`)
)

const html = computed(() => {
  const content = article.value?.content
  if (!content) return ''
  // async: false 强制同步返回字符串，避免拿到 Promise
  return marked.parse(content, { async: false, gfm: true, breaks: true }) as string
})

useSeoMeta({
  title: () => article.value?.title ?? '文章',
  description: () => article.value?.summary ?? '',
  ogTitle: () => article.value?.title ?? '',
  ogDescription: () => article.value?.summary ?? '',
  ogImage: () => article.value?.cover_url || undefined,
  ogType: 'article'
})

if (!article.value && error.value) {
  throw createError({ statusCode: 404, statusMessage: '文章不存在', fatal: true })
}
</script>

<template>
  <article v-if="article">
    <!-- 返回：小、安静，不抢标题 -->
    <NuxtLink
      to="/"
      class="mb-10 inline-flex items-center gap-1.5 text-sm text-stone-400 transition-colors
             hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-100"
    >
      <UIcon
        name="i-lucide-arrow-left"
        class="size-4"
      />
      返回列表
    </NuxtLink>

    <header class="mb-10">
      <h1 class="font-serif text-[1.9rem] leading-tight font-semibold text-stone-900 sm:text-[2.4rem] dark:text-stone-100">
        {{ article.title }}
      </h1>

      <div class="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-400 dark:text-stone-500">
        <time>{{ formatDate(article.created_at) }}</time>
        <span class="text-stone-300 dark:text-stone-700">/</span>
        <span>{{ readingTime(article.content) }}</span>
        <template v-if="article.category">
          <span class="text-stone-300 dark:text-stone-700">/</span>
          <span>{{ article.category.name }}</span>
        </template>
        <span class="text-stone-300 dark:text-stone-700">/</span>
        <span>{{ article.views }} 次阅读</span>
      </div>

      <img
        v-if="article.cover_url"
        :src="article.cover_url"
        :alt="article.title"
        class="mt-8 w-full rounded-lg object-cover"
      >
    </header>

    <!--
      正文由管理员撰写，属于可信内容，不做 HTML 过滤；
      article-body 是 main.css 里定义的排版类，Tailwind 插件不认识这个自定义类名。
    -->
    <!-- eslint-disable vue/no-v-html, better-tailwindcss/no-unknown-classes -->
    <div
      class="article-body"
      v-html="html"
    />
    <!-- eslint-enable vue/no-v-html, better-tailwindcss/no-unknown-classes -->

    <!-- 文末：标签 + 署名 -->
    <footer class="mt-16 border-t border-stone-200 pt-8 dark:border-stone-800">
      <div
        v-if="article.tags.length"
        class="flex flex-wrap items-center gap-2"
      >
        <span class="text-xs text-stone-400 dark:text-stone-500">标签</span>
        <NuxtLink
          v-for="tag in article.tags"
          :key="tag.id"
          :to="{ path: '/', query: { tag: tag.id } }"
          class="rounded-full border border-stone-200 px-3 py-1 text-xs text-stone-500 transition-colors
                 hover:border-stone-400 hover:text-stone-900
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        >
          {{ tag.name }}
        </NuxtLink>
      </div>

      <p class="mt-8 text-sm text-stone-400 dark:text-stone-500">
        本文作者 {{ article.author_name }}，转载请注明出处。
      </p>
    </footer>
  </article>
</template>
