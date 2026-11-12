<script setup lang="ts">
/**
 * 后台布局：左侧导航 + 右侧内容。
 *
 * 与前台布局分开，是因为信息密度完全不同 —— 前台要留白，
 * 后台要一眼看到所有入口。
 *
 * 用 grid 而不是「fixed 侧边栏 + 内容区 margin-left」：
 * 后者要求两处宽度严格一致，改一处忘另一处就会重叠。
 * grid 的列宽一处定义，两边自动对齐。
 *
 * 高度锁在 h-screen + overflow-hidden：后台的滚动条交给页面内部的列表区
 * （见 main.css 的 .admin-shell），整页不滚。这样翻页、筛完再翻页时，
 * 标题和筛选条始终停在原位，不用先滚回顶部。
 *
 * ⚠️ 列宽写成内联 style，不用 `grid-cols-[13rem_1fr]`：
 * 实测这个版本的 Tailwind 不生成任意值类（编译产物里连 13rem 都搜不到），
 * 写了等于没写，布局会塌成单列。
 */
const route = useRoute()
const { user, logout } = useAuth()

const nav = [
  { label: '文章', to: '/admin/articles', icon: 'i-lucide-file-text' },
  { label: '分类标签', to: '/admin/taxonomy', icon: 'i-lucide-folder-tree' },
  { label: '评论', to: '/admin/comments', icon: 'i-lucide-message-square' },
  { label: '用户', to: '/admin/users', icon: 'i-lucide-users' },
  { label: 'AI 模型', to: '/admin/llm', icon: 'i-lucide-sparkles' }
]

function isActive(to: string) {
  return route.path.startsWith(to)
}

async function handleLogout() {
  await logout()
  await navigateTo('/')
}
</script>

<template>
  <div
    class="grid h-screen overflow-hidden bg-white dark:bg-stone-950"
    style="grid-template-columns: 13rem 1fr"
  >
    <!-- 侧边栏：sticky 而不是 fixed，跟着 grid 走，不需要额外偏移 -->
    <aside
      class="flex h-full flex-col overflow-y-auto border-r border-stone-200
             bg-stone-50/70 dark:border-stone-800 dark:bg-stone-900/40"
    >
      <div class="px-5 py-6">
        <NuxtLink
          to="/"
          class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100"
        >
          之间
        </NuxtLink>
        <p class="mt-1 text-[11px] text-stone-400 dark:text-stone-600">
          后台管理
        </p>
      </div>

      <nav class="flex-1 space-y-0.5 px-3">
        <NuxtLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors"
          :class="isActive(item.to)
            ? 'bg-stone-900 text-white dark:bg-stone-100 dark:text-stone-900'
            : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100'"
        >
          <UIcon
            :name="item.icon"
            class="size-4 shrink-0"
          />
          {{ item.label }}
        </NuxtLink>
      </nav>

      <div class="border-t border-stone-200 p-3 dark:border-stone-800">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="truncate text-xs text-stone-500 dark:text-stone-400">
            {{ user?.name }}
          </span>
          <button
            type="button"
            class="shrink-0 text-xs text-stone-400 transition-colors hover:text-stone-900 dark:hover:text-stone-100"
            @click="handleLogout"
          >
            退出
          </button>
        </div>
        <NuxtLink
          to="/"
          class="mt-1 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-stone-400
                 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-100"
        >
          <UIcon
            name="i-lucide-arrow-left"
            class="size-3.5"
          />
          返回前台
        </NuxtLink>
      </div>
    </aside>

    <!-- 内容区：min-w-0 防止表格把 grid 撑破；overflow-hidden 交给页面自己决定哪里滚 -->
    <div class="min-w-0 overflow-hidden">
      <main class="mx-auto flex h-full max-w-5xl flex-col px-8 py-8">
        <slot />
      </main>
    </div>
  </div>
</template>
