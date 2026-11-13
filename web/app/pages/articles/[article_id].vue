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
const { isLoggedIn } = useAuth()

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

/**
 * 点赞状态。
 *
 * 独立成本地状态而不是直接改 `article`：`useAsyncData` 的数据是服务端
 * 取回来的，客户端改动会被后续刷新覆盖，点赞这种高频交互必须自己持有。
 *
 * SSR 阶段拿不到登录态，`is_liked` 一定是 false —— 客户端 hydration 后
 * 用户如果点进来过，这个值会由接口在下次加载时纠正。
 */
const liked = ref(false)
const likeCount = ref(0)
const likeLoading = ref(false)

watch(
  article,
  (value) => {
    if (!value) return
    liked.value = value.is_liked
    likeCount.value = value.like_count
  },
  { immediate: true }
)

/** 点赞 / 取消点赞。未登录先去登录，登录后回到本文。 */
async function toggleLike() {
  if (!isLoggedIn.value) {
    await navigateTo({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  if (likeLoading.value) return

  likeLoading.value = true
  // 先改本地状态：点赞是高频轻操作，等接口回来再变会显得卡
  const next = !liked.value
  liked.value = next
  likeCount.value += next ? 1 : -1

  try {
    await api.request(`/articles/${articleId.value}/like`, {
      method: next ? 'POST' : 'DELETE'
    })
  } catch {
    // 失败回滚，避免界面与服务端长期不一致
    liked.value = !next
    likeCount.value += next ? -1 : 1
  } finally {
    likeLoading.value = false
  }
}

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

      <!--
        封面不在这里显示：它是列表页用来「一眼区分文章」的缩略图，
        详情页有大标题和正文，再摆一张大图只会把正文推到首屏之外。
        但 og:image 仍用 cover_url —— 分享到社交平台时那张图是必要的。
      -->
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

      <!-- 点赞：放在文末，读完才会想点 -->
      <div class="mt-10 flex items-center gap-4">
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm
                 transition-colors"
          :class="liked
            ? 'border-rose-200 text-rose-600 dark:border-rose-900 dark:text-rose-400'
            : 'border-stone-200 text-stone-500 hover:border-stone-400 hover:text-stone-900 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100'"
          :disabled="likeLoading"
          @click="toggleLike"
        >
          <UIcon
            name="i-lucide-heart"
            class="size-4"
            :class="liked ? 'fill-current' : ''"
          />
          {{ likeCount }}
        </button>

        <span class="text-xs text-stone-300 dark:text-stone-600">
          {{ article.comment_count }} 条评论
        </span>
      </div>

      <p class="mt-8 text-sm text-stone-400 dark:text-stone-500">
        本文作者 {{ article.author_name }}，转载请注明出处。
      </p>
    </footer>

    <!-- 评论 -->
    <CommentSection :article-id="article.id" />
  </article>
</template>
