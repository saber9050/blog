<script setup lang="ts">
/**
 * 认证页布局：居中的窄栏，不显示导航。
 *
 * 登录、注册、找回密码共用。刻意去掉顶部导航 —— 认证流程里多一个出口
 * 只会让人分心。
 */
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <header class="px-6 py-8">
      <NuxtLink
        to="/"
        class="font-serif text-base font-semibold tracking-tight text-stone-900 dark:text-stone-100"
      >
        之间
      </NuxtLink>
    </header>

    <main class="flex flex-1 items-start justify-center px-6 pb-24 pt-6">
      <div class="w-full max-w-[22rem]">
        <slot />
      </div>
    </main>

    <footer class="px-6 py-8 text-center text-xs text-stone-400 dark:text-stone-600">
      用文字留住时间
    </footer>
  </div>
</template>
