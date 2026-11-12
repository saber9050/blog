<script setup lang="ts">
import type { About } from '~/types/api'

/**
 * 关于页。
 *
 * 数据来自单例表，字段全可能为空（新站还没填）。页面结构照常渲染，
 * 空字段直接不显示，不做「暂无内容」的占位 —— 空白比占位文案更干净。
 */
const api = useApi()

const { data: about } = await useAsyncData('about', () => api.request<About>('/about'))

useSeoMeta({
  title: '关于',
  description: () => about.value?.introduction || '关于这个站点和它的作者。'
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

/** 几个长文本区块，顺序固定，空的不渲染。 */
const sections = computed(() => {
  const a = about.value
  if (!a) return []
  return [
    { title: '技术栈', body: a.tech_stack },
    { title: '我的故事', body: a.my_story },
    { title: '为什么写', body: a.why },
    { title: '兴趣', body: a.interest }
  ].filter(item => item.body)
})
</script>

<template>
  <div v-if="about">
    <!-- 头部：头像 + 名字 + 一句话 -->
    <header class="flex items-center gap-5">
      <img
        v-if="about.avatar_url"
        :src="about.avatar_url"
        :alt="about.admin_name"
        class="size-16 rounded-full object-cover"
      >
      <div
        v-else
        class="flex size-16 items-center justify-center rounded-full bg-stone-100 text-xl
               font-serif text-stone-400 dark:bg-stone-800 dark:text-stone-500"
      >
        {{ about.admin_name.slice(0, 1) }}
      </div>

      <div>
        <h1 class="font-serif text-2xl font-semibold text-stone-900 dark:text-stone-100">
          {{ about.admin_name }}
        </h1>
        <p
          v-if="about.introduction"
          class="mt-1 text-sm text-stone-500 dark:text-stone-400"
        >
          {{ about.introduction }}
        </p>
      </div>
    </header>

    <!-- 长文本区块 -->
    <div
      v-if="sections.length"
      class="mt-14 space-y-12"
    >
      <section
        v-for="section in sections"
        :key="section.title"
      >
        <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
          {{ section.title }}
        </h2>
        <p class="mt-4 whitespace-pre-line text-[0.95rem] leading-[1.9] text-stone-600 dark:text-stone-400">
          {{ section.body }}
        </p>
      </section>
    </div>

    <!-- 还没填任何内容时 -->
    <p
      v-else
      class="mt-14 text-sm text-stone-400"
    >
      这里还空着，等作者想起要写点什么。
    </p>

    <!-- 社交链接 -->
    <div
      v-if="links.length"
      class="mt-14 flex flex-wrap gap-3 border-t border-stone-200 pt-8 dark:border-stone-800"
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
  </div>
</template>
