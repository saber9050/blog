<script setup lang="ts">
/**
 * 应用根组件。
 *
 * 做三件事：挂 `<UApp>`（tooltip / toast 等需要它提供的上下文）、
 * 放一个全站唯一的确认框（替代原生 `window.confirm`）、交给布局系统渲染页面。
 * 导航和页脚都在 `layouts/default.vue` 里。
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

    <!-- 挂在根上：前后台共用，避免每个布局各放一份 -->
    <ConfirmDialog />
  </UApp>
</template>
