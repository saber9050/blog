<script setup lang="ts">
/**
 * 前台布局：极简导航 + 内容区 + 页脚。
 *
 * 导航做三件事就够：回首页、去归档、去关于。
 * 不放搜索框和分类下拉 —— 那些属于首页内容，塞进导航只会让顶部变重。
 */

const nav = [
  { label: '文章', to: '/' },
  { label: '归档', to: '/archive' },
  { label: '关于', to: '/about' }
]

const route = useRoute()
const colorMode = useColorMode()

function isActive(to: string) {
  return to === '/' ? route.path === '/' : route.path.startsWith(to)
}

function toggleTheme() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header
      class="sticky top-0 z-50 border-b border-stone-200/70 bg-[#fcfcfa]/80 backdrop-blur-md
             dark:border-stone-800/70 dark:bg-stone-950/80"
    >
      <div class="mx-auto flex h-16 max-w-3xl items-center justify-between px-6">
        <NuxtLink
          to="/"
          class="font-serif text-lg font-semibold tracking-tight text-stone-900 dark:text-stone-100"
        >
          之间
        </NuxtLink>

        <nav class="flex items-center gap-1">
          <NuxtLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="rounded-md px-3 py-1.5 text-sm transition-colors"
            :class="isActive(item.to)
              ? 'text-stone-900 dark:text-stone-100'
              : 'text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100'"
          >
            {{ item.label }}
          </NuxtLink>

          <button
            type="button"
            class="ml-1 rounded-md p-2 text-stone-500 transition-colors hover:text-stone-900
                   dark:text-stone-400 dark:hover:text-stone-100"
            :aria-label="colorMode.value === 'dark' ? '切换到浅色' : '切换到深色'"
            @click="toggleTheme"
          >
            <UIcon
              :name="colorMode.value === 'dark' ? 'i-lucide-sun' : 'i-lucide-moon'"
              class="size-4"
            />
          </button>
        </nav>
      </div>
    </header>

    <main class="mx-auto w-full max-w-3xl flex-1 px-6 py-14">
      <slot />
    </main>

    <footer class="border-t border-stone-200 py-10 dark:border-stone-800">
      <div
        class="mx-auto flex max-w-3xl flex-col items-center justify-between gap-3 px-6
               text-sm text-stone-400 sm:flex-row dark:text-stone-500"
      >
        <p>© {{ new Date().getFullYear() }} 之间 · 用文字留住时间</p>
        <div class="flex items-center gap-4">
          <a
            href="https://github.com/saber9050"
            target="_blank"
            rel="noopener"
            class="transition-colors hover:text-stone-900 dark:hover:text-stone-100"
          >GitHub</a>
          <NuxtLink
            to="/about"
            class="transition-colors hover:text-stone-900 dark:hover:text-stone-100"
          >关于</NuxtLink>
        </div>
      </div>
    </footer>
  </div>
</template>
