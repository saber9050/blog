<script setup lang="ts">
/**
 * 应用根组件。
 *
 * 只做两件事：挂 `<UApp>`（tolltip / toast 等需要它提供的上下文）、
 * 交给布局系统渲染页面。导航和页脚都在 `layouts/default.vue` 里。
 */
useHead({
  link: [{ rel: 'icon', href: '/favicon.ico' }]
})
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </UApp>
</template>
