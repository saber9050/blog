<script setup lang="ts">
/**
 * `/admin` 本身不做页面，直接进文章管理 —— 后台最高频的操作就是它。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

await navigateTo('/admin/articles', { replace: true })
</script>

<template>
  <div />
</template>
