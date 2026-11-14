<script setup lang="ts">
import type { About, Article, PageResult, Taxonomy } from '~/types/api'

/**
 * 关于页。
 *
 * 数据分两层：
 *
 * 1. **站点数据（自动）**：文章 / 分类 / 标签数量，从现有接口取。
 *    这些永远有值，页面不会因为「作者还没来得及填资料」而空掉。
 * 2. **作者自述（手填）**：名字、头像、简介、社交链接来自 about 单例表。
 *
 * about 表里的长文本字段（技术栈 / 我的故事 / 为什么写 / 兴趣）目前**没有后台编辑入口**，
 * 所以这里给了一套基于项目事实的默认内容：有值就用作者的，没值就用默认的。
 * 注意默认文案只描述「这个站点是什么」，不编造作者的个人经历 ——
 * 那种内容只能由本人写。
 */
const api = useApi()

const { data: about } = await useAsyncData('about', () => api.request<About>('/about'))

/**
 * 站点数据。
 *
 * `/articles` 只取 1 条，是为了拿 `total`，顺带省流量；
 * 分类和标签接口不分页，返回全量数组。
 */
const { data: counts } = await useAsyncData('about-counts', async () => {
  const [articles, categories, tags] = await Promise.all([
    api.request<PageResult<Article>>('/articles', { query: { page: 1, page_size: 1 } }),
    api.request<Taxonomy[]>('/categories'),
    api.request<Taxonomy[]>('/tags')
  ])
  return {
    articles: articles.total,
    categories: categories.length,
    tags: tags.length
  }
})

useSeoMeta({
  title: '关于',
  description: () => about.value?.introduction || '关于这个站点和它的作者。'
})

/** 数字区。三项都是真实统计，不写「运行天数」这类需要额外接口的值。 */
const stats = computed(() => [
  { label: '篇文章', value: counts.value?.articles ?? 0 },
  { label: '个分类', value: counts.value?.categories ?? 0 },
  { label: '个标签', value: counts.value?.tags ?? 0 }
])

/** 技术栈：按层分组，全部是本项目实际用到的，不凑数。 */
const stack = [
  { label: '后端', items: ['Python', 'FastAPI', 'SQLAlchemy', 'MySQL 8', 'Redis', 'MinIO'] },
  { label: '前端', items: ['Nuxt 4', 'Vue 3', 'TypeScript', 'Tailwind CSS'] },
  { label: '工程', items: ['Alembic', 'Docker Compose', 'GitHub Actions', 'pytest'] }
]

/**
 * 「这个站点」正文。
 *
 * 作者在 about 表里写过 `my_story` 就用他的，按空行拆段；
 * 没写则用这段基于项目事实的描述 —— 只讲站点是什么，不编造个人经历。
 */
const siteParagraphs = computed(() => {
  const custom = about.value?.my_story?.trim()
  if (custom) return custom.split(/\n{2,}/).filter(Boolean)

  return [
    '这是一个自己写、自己维护的个人博客。后端把原来的 Go 版本用 FastAPI 重写了一遍，接口契约保持一致；'
    + '前端是 Nuxt 4 的服务端渲染站点，追求「像一张纸」的阅读体验 —— 低饱和配色、大量留白、标题用衬线。',
    '文章用 Markdown 写，支持图片上传与代码块；评论两级嵌套；'
    + '后台带文章、分类、评论、用户和 AI 摘要的管理。没有主题市场，也没有插件体系，只有这一套东西。'
  ]
})

/** 有值才展示的社交链接，避免渲染一堆空链接。 */
const links = computed(() => {
  const a = about.value
  if (!a) return []
  return [
    { label: 'GitHub', href: a.git_hub, icon: 'i-simple-icons-github' },
    { label: 'CSDN', href: a.csdn, icon: 'i-simple-icons-csdn' },
    { label: '邮箱', href: a.email ? `mailto:${a.email}` : '', icon: 'i-lucide-mail' }
  ].filter(item => item.href)
})
</script>

<template>
  <div v-if="about">
    <!-- 头部：头像 + 名字 + 一句话 -->
    <header class="flex items-center gap-6 sm:gap-9">
      <img
        v-if="about.avatar_url"
        :src="about.avatar_url"
        :alt="about.admin_name"
        class="size-16 shrink-0 rounded-full object-cover ring-1 ring-stone-200 sm:size-24 dark:ring-stone-800"
      >
      <div
        v-else
        class="flex size-16 shrink-0 items-center justify-center rounded-full bg-stone-100 font-serif
               text-xl text-stone-400 sm:size-24 sm:text-2xl dark:bg-stone-800 dark:text-stone-500"
      >
        {{ about.admin_name.slice(0, 1) }}
      </div>

      <div class="min-w-0">
        <p class="text-[11px] tracking-[0.25em] text-stone-400 uppercase dark:text-stone-600">
          About
        </p>
        <h1 class="mt-2 font-serif text-[1.75rem] leading-tight font-semibold text-stone-900 sm:text-[2.2rem] dark:text-stone-100">
          {{ about.admin_name }}
        </h1>
        <p
          v-if="about.introduction"
          class="mt-2 text-sm leading-relaxed text-stone-500 dark:text-stone-400"
        >
          {{ about.introduction }}
        </p>
      </div>
    </header>

    <!-- 引言：一句态度，字号拉开，把版面从「资料页」变成「文章页」 -->
    <blockquote class="mt-16 border-l-2 border-stone-300 pl-6 dark:border-stone-700">
      <p class="font-serif text-xl leading-relaxed text-stone-700 sm:text-2xl dark:text-stone-300">
        写代码，也写为什么。
      </p>
    </blockquote>

    <!-- 数字：真实统计。用竖线分隔，比三个孤零零的数字更像一条「统计带」 -->
    <dl
      v-if="counts"
      class="mt-16 grid grid-cols-3 border-y border-stone-200 py-8 dark:border-stone-800"
    >
      <div
        v-for="item in stats"
        :key="item.label"
        class="border-l border-stone-200 pl-5 first:border-l-0 first:pl-0 sm:pl-8 dark:border-stone-800"
      >
        <dd class="font-serif text-3xl font-semibold tabular-nums text-stone-900 sm:text-4xl dark:text-stone-100">
          {{ item.value }}
        </dd>
        <dt class="mt-1.5 text-[11px] text-stone-400 dark:text-stone-500">
          {{ item.label }}
        </dt>
      </div>
    </dl>

    <!-- 这个站点 -->
    <section class="mt-16">
      <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
        这个站点
      </h2>
      <div class="mt-4 space-y-4">
        <p
          v-for="(paragraph, index) in siteParagraphs"
          :key="index"
          class="text-[0.95rem] leading-[1.9] text-stone-600 dark:text-stone-400"
        >
          {{ paragraph }}
        </p>
      </div>
    </section>

    <!-- 技术栈：分组 chip。作者在 about 里自定义过就改用他的文字版本 -->
    <section
      v-if="!about.tech_stack"
      class="mt-14"
    >
      <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
        技术栈
      </h2>
      <div class="mt-5 space-y-3">
        <div
          v-for="group in stack"
          :key="group.label"
          class="flex flex-wrap items-baseline gap-x-3 gap-y-2"
        >
          <span class="w-10 shrink-0 text-[11px] text-stone-400 dark:text-stone-500">
            {{ group.label }}
          </span>
          <span
            v-for="tech in group.items"
            :key="tech"
            class="rounded-full border border-stone-200 px-2.5 py-1 text-[11px] text-stone-600
                   dark:border-stone-800 dark:text-stone-400"
          >
            {{ tech }}
          </span>
        </div>
      </div>
    </section>

    <!-- 作者额外写的段落（有才显示，没填就不占版面） -->
    <div
      v-if="about.why || about.interest || about.tech_stack"
      class="mt-14 space-y-10"
    >
      <section v-if="about.why">
        <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
          为什么写
        </h2>
        <p class="mt-4 whitespace-pre-line text-[0.95rem] leading-[1.9] text-stone-600 dark:text-stone-400">
          {{ about.why }}
        </p>
      </section>

      <section v-if="about.interest">
        <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
          兴趣
        </h2>
        <p class="mt-4 whitespace-pre-line text-[0.95rem] leading-[1.9] text-stone-600 dark:text-stone-400">
          {{ about.interest }}
        </p>
      </section>

      <section v-if="about.tech_stack">
        <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
          技术栈
        </h2>
        <p class="mt-4 whitespace-pre-line text-[0.95rem] leading-[1.9] text-stone-600 dark:text-stone-400">
          {{ about.tech_stack }}
        </p>
      </section>
    </div>

    <!-- 联系 -->
    <footer class="mt-16 border-t border-stone-200 pt-8 dark:border-stone-800">
      <p class="text-[11px] tracking-[0.25em] text-stone-400 uppercase dark:text-stone-600">
        Contact
      </p>
      <div
        v-if="links.length"
        class="mt-4 flex flex-wrap gap-3"
      >
        <a
          v-for="link in links"
          :key="link.label"
          :href="link.href"
          target="_blank"
          rel="noopener"
          class="inline-flex items-center gap-2 rounded-full border border-stone-200 px-4 py-1.5
                 text-sm text-stone-600 transition-colors hover:border-stone-400 hover:text-stone-900
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        >
          <UIcon
            :name="link.icon"
            class="size-4"
          />
          {{ link.label }}
        </a>
      </div>
      <p
        v-else
        class="mt-3 text-sm text-stone-400 dark:text-stone-500"
      >
        还没有公开的联系方式。
      </p>

      <p class="mt-7 text-[11px] text-stone-400 dark:text-stone-600">
        本站由 FastAPI 与 Nuxt 4 驱动，界面与文章均为原创。
      </p>
    </footer>
  </div>
</template>
