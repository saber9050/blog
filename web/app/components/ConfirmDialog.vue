<script setup lang="ts">
/**
 * 全站确认框。由 `app.vue` 挂载，一次即可。
 *
 * 用 `<Teleport to="body">` 而不是就地渲染：后台布局是
 * `h-screen overflow-hidden`（列表内部滚动），就地渲染会被祖先的
 * overflow 裁掉，或者被 sticky 元素的层叠上下文压住。
 */
const { state, settle } = useConfirm()

/** Esc = 取消。只在打开时监听，避免全站常驻一个 keydown 处理器。 */
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') settle(false)
}

watch(
  () => state.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  }
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      leave-active-class="transition duration-100 ease-in"
      leave-to-class="opacity-0"
    >
      <div
        v-if="state.open"
        class="fixed inset-0 z-100 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
      >
        <!-- 遮罩：点一下等于取消，和大部分桌面应用的习惯一致 -->
        <div
          class="absolute inset-0 bg-stone-900/25 backdrop-blur-[2px] dark:bg-black/50"
          @click="settle(false)"
        />

        <div
          class="relative w-full max-w-sm rounded-lg border border-stone-200 bg-white p-5
                 shadow-xl shadow-stone-900/5 dark:border-stone-800 dark:bg-stone-900"
        >
          <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
            {{ state.title }}
          </h2>

          <p
            v-if="state.description"
            class="mt-2 text-xs leading-relaxed text-stone-500 dark:text-stone-400"
          >
            {{ state.description }}
          </p>

          <div class="mt-6 flex items-center justify-end gap-3">
            <button
              type="button"
              class="rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
                     transition-colors hover:border-stone-400 hover:text-stone-900
                     dark:border-stone-700 dark:text-stone-400 dark:hover:border-stone-500
                     dark:hover:text-stone-100"
              @click="settle(false)"
            >
              {{ state.cancelText || '取消' }}
            </button>
            <button
              type="button"
              class="rounded-md px-4 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
              :class="state.danger ? 'bg-rose-600' : 'bg-stone-900 dark:bg-stone-100 dark:text-stone-900'"
              @click="settle(true)"
            >
              {{ state.confirmText || '确定' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
