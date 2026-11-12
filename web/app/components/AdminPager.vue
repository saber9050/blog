<script setup lang="ts">
/**
 * 后台通用分页条。
 *
 * 五个后台列表（文章 / 评论 / 用户 / 分类标签 / AI 模型）的分页行为完全一样：
 * 左侧总数 + 每页条数，右侧上一页 / 页码 / 下一页。
 * 抽成一个组件而不是复制五遍，改一次全站生效。
 *
 * 组件本身不持有状态：页码和每页条数都由父页面 ref 控制，
 * 通过 v-model:page / v-model:page-size 双向绑定。
 * 「改每页条数要回到第 1 页」这种业务规则留给父页面处理 ——
 * 组件不知道数据是怎么来的（服务端分页还是前端切片）。
 */
const props = withDefaults(defineProps<{
  /** 当前页，从 1 开始 */
  page: number
  /** 总条数（不是总页数） */
  total: number
  /** 每页条数 */
  pageSize: number
  /** 可选的每页条数档位 */
  pageSizes?: number[]
}>(), {
  pageSizes: () => [10, 20, 50, 100]
})

const emit = defineEmits<{
  'update:page': [value: number]
  'update:pageSize': [value: number]
}>()

/** 总页数至少为 1，否则「1 / 0」这种显示会出现在空列表上。 */
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

function go(next: number) {
  if (next === props.page || next < 1 || next > totalPages.value) return
  emit('update:page', next)
}

function changeSize(event: Event) {
  const size = Number((event.target as HTMLSelectElement).value)
  if (size && size !== props.pageSize) emit('update:pageSize', size)
}
</script>

<template>
  <div class="flex shrink-0 flex-wrap items-center justify-between gap-3 text-xs">
    <div class="flex items-center gap-2">
      <span class="text-stone-400 dark:text-stone-500">共 {{ total }} 条</span>
      <select
        :value="pageSize"
        class="rounded-md border border-stone-200 bg-transparent px-2 py-1 text-xs
               text-stone-500 outline-none dark:border-stone-800 dark:text-stone-400"
        @change="changeSize"
      >
        <option
          v-for="size in pageSizes"
          :key="size"
          :value="size"
        >
          {{ size }} 条/页
        </option>
      </select>
    </div>

    <div class="flex items-center gap-4">
      <button
        type="button"
        :disabled="page <= 1"
        class="text-stone-500 transition-colors hover:text-stone-900 disabled:text-stone-300
               dark:text-stone-400 dark:hover:text-stone-100 dark:disabled:text-stone-700"
        @click="go(page - 1)"
      >
        上一页
      </button>
      <span class="tabular-nums text-stone-400 dark:text-stone-500">{{ page }} / {{ totalPages }}</span>
      <button
        type="button"
        :disabled="page >= totalPages"
        class="text-stone-500 transition-colors hover:text-stone-900 disabled:text-stone-300
               dark:text-stone-400 dark:hover:text-stone-100 dark:disabled:text-stone-700"
        @click="go(page + 1)"
      >
        下一页
      </button>
    </div>
  </div>
</template>
