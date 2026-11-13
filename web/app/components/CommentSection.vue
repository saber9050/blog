<script setup lang="ts">
import type { Comment, PageResult } from '~/types/api'

/**
 * 文章评论。
 *
 * 后端的两级结构有两个反直觉的地方，前端必须照着来：
 *
 * 1. **排序方向相反**：一级评论按时间倒序（新的在上），二级回复按时间正序
 *    （对话顺序，早的在上）。
 * 2. **已删除的评论仍会返回**，`is_deleted: true` 且 `content` 为空。
 *    不能过滤掉 —— 它的回复还挂在下面，隐藏了一级会让回复失去上下文。
 */
const props = defineProps<{ articleId: number }>()

const api = useApi()
const { isLoggedIn, isAdmin, user } = useAuth()
const { confirm } = useConfirm()

const comments = ref<Comment[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const submitting = ref(false)
const error = ref('')

const content = ref('')
const replyTo = ref<Comment | null>(null)

/** 二级回复的缓存与状态，按一级评论 ID 索引。 */
const replies = reactive<Record<number, Comment[]>>({})
const expanded = reactive<Record<number, boolean>>({})
const replyLoading = reactive<Record<number, boolean>>({})

const PAGE_SIZE = 20
const REPLY_PAGE_SIZE = 30

const remaining = computed(() => Math.max(0, total.value - comments.value.length))

/** 加载一级评论。reset 为 true 时从头拉（发布/删除后调用）。 */
async function load(reset = false) {
  if (loading.value) return
  loading.value = true
  error.value = ''

  try {
    const target = reset ? 1 : page.value
    const res = await api.request<PageResult<Comment>>(
      `/articles/${props.articleId}/comments`,
      { query: { page: target, page_size: PAGE_SIZE } }
    )
    comments.value = reset ? res.list : [...comments.value, ...res.list]
    total.value = res.total
    page.value = target + 1
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '评论加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => load(true))

/**
 * 拉取某条评论的二级回复。
 *
 * 首次展开时才请求 —— 一进页面就给每条评论打一个请求，20 条评论就是 20 个
 * 并发请求，而用户可能一条回复都不看。
 *
 * @param force 强制重拉（发布/删除回复后缓存已失效）
 */
async function loadReplies(comment: Comment, force = false) {
  expanded[comment.id] = true
  if (replies[comment.id]?.length && !force) return

  replyLoading[comment.id] = true
  try {
    const res = await api.request<PageResult<Comment>>(
      `/articles/${props.articleId}/comments/${comment.id}/replies`,
      { query: { page: 1, page_size: REPLY_PAGE_SIZE } }
    )
    replies[comment.id] = res.list
  } catch {
    replies[comment.id] = []
  } finally {
    replyLoading[comment.id] = false
  }
}

/** 展开 / 收起某条评论的回复。 */
async function toggleReplies(comment: Comment) {
  if (expanded[comment.id]) {
    expanded[comment.id] = false
    return
  }
  await loadReplies(comment)
}

/** 点「回复」：把目标记下来，输入框聚焦并提示回复对象。 */
function startReply(comment: Comment) {
  replyTo.value = comment
  nextTick(() => {
    document.getElementById('comment-input')?.focus()
  })
}

function cancelReply() {
  replyTo.value = null
}

async function submit() {
  if (!isLoggedIn.value) {
    await navigateTo({ path: '/login', query: { redirect: `/articles/${props.articleId}` } })
    return
  }
  if (submitting.value || !content.value.trim()) return

  submitting.value = true
  error.value = ''

  try {
    await api.request(`/articles/${props.articleId}/comments`, {
      method: 'POST',
      body: {
        content: content.value.trim(),
        ...(replyTo.value
          ? { parent_id: replyTo.value.id, reply_to_name: replyTo.value.user_name }
          : {})
      }
    })
    content.value = ''
    const parent = replyTo.value
    replyTo.value = null

    // 回复的话刷新对应父评论的回复列表，否则重拉一级列表
    if (parent) {
      await loadReplies(parent, true)
    }
    await load(true)
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '发布失败'
  } finally {
    submitting.value = false
  }
}

async function remove(comment: Comment) {
  const ok = await confirm({
    title: '删除这条评论？',
    description: '删除后不可恢复，它下面的回复会保留。',
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
  try {
    await api.request(`/articles/${props.articleId}/comments/${comment.id}`, { method: 'DELETE' })
    // 回复缓存作废：清空后再次展开会重新请求
    replies[comment.id] = []
    expanded[comment.id] = false
    await load(true)
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

/** 能不能删：作者本人或管理员。 */
function canDelete(comment: Comment): boolean {
  return isAdmin.value || user.value?.id === comment.user_id
}
</script>

<template>
  <section class="mt-16 border-t border-stone-200 pt-12 dark:border-stone-800">
    <div class="flex items-baseline justify-between">
      <h2 class="font-serif text-lg font-semibold text-stone-900 dark:text-stone-100">
        评论
      </h2>
      <span class="text-xs text-stone-400 dark:text-stone-500">
        {{ total }} 条
      </span>
    </div>

    <!-- 输入区：未登录时引导登录，不显示禁用的输入框 -->
    <div class="mt-6">
      <div
        v-if="!isLoggedIn"
        class="text-sm text-stone-400 dark:text-stone-500"
      >
        <NuxtLink
          :to="{ path: '/login', query: { redirect: `/articles/${articleId}` } }"
          class="text-stone-600 underline decoration-stone-300 underline-offset-4 transition-colors
                 hover:text-stone-900 dark:text-stone-300 dark:decoration-stone-700 dark:hover:text-stone-100"
        >
          登录
        </NuxtLink>
        后参与讨论
      </div>

      <div v-else>
        <div
          v-if="replyTo"
          class="mb-2 flex items-center gap-2 text-xs text-stone-400 dark:text-stone-500"
        >
          正在回复 {{ replyTo.user_name }}
          <button
            type="button"
            class="text-stone-400 underline underline-offset-2 hover:text-stone-600"
            @click="cancelReply"
          >
            取消
          </button>
        </div>

        <textarea
          id="comment-input"
          v-model="content"
          rows="3"
          :placeholder="replyTo ? `回复 ${replyTo.user_name}…` : '说点什么…'"
          class="w-full resize-none rounded-lg border border-stone-200 bg-transparent px-4 py-3 text-sm
                 text-stone-800 outline-none transition-colors placeholder:text-stone-300
                 focus:border-stone-400 dark:border-stone-800 dark:text-stone-200
                 dark:placeholder:text-stone-600 dark:focus:border-stone-600"
        />

        <div class="mt-3 flex items-center justify-between">
          <p
            v-if="error"
            class="text-xs text-rose-600 dark:text-rose-400"
          >
            {{ error }}
          </p>
          <span
            v-else
            class="text-xs text-stone-300 dark:text-stone-600"
          >
            Markdown 不支持，纯文本
          </span>

          <button
            type="button"
            :disabled="submitting || !content.trim()"
            class="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
                   transition-opacity hover:opacity-90 disabled:opacity-30
                   dark:bg-stone-100 dark:text-stone-900"
            @click="submit"
          >
            {{ submitting ? '发布中…' : '发布' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 列表 -->
    <div
      v-if="loading && comments.length === 0"
      class="mt-10 text-sm text-stone-400"
    >
      加载中…
    </div>

    <div
      v-else-if="comments.length === 0"
      class="mt-10 text-sm text-stone-400 dark:text-stone-500"
    >
      还没有评论，来做第一个。
    </div>

    <ul
      v-else
      class="mt-10 space-y-8"
    >
      <li
        v-for="comment in comments"
        :key="comment.id"
      >
        <div class="flex gap-3">
          <img
            v-if="comment.avatar_url"
            :src="comment.avatar_url"
            :alt="comment.user_name"
            class="size-8 shrink-0 rounded-full object-cover"
          >
          <div
            v-else
            class="flex size-8 shrink-0 items-center justify-center rounded-full bg-stone-100
                   text-xs text-stone-400 dark:bg-stone-800 dark:text-stone-500"
          >
            {{ comment.is_deleted ? '?' : comment.user_name.slice(0, 1) }}
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2">
              <span class="text-sm font-medium text-stone-700 dark:text-stone-300">
                {{ comment.is_deleted ? '已注销用户' : comment.user_name }}
              </span>
              <time class="text-xs text-stone-300 dark:text-stone-600">
                {{ formatRelative(comment.created_at) }}
              </time>
            </div>

            <!-- 已删评论：保留占位，因为它的回复还挂在下面 -->
            <p
              v-if="comment.is_deleted"
              class="mt-2 text-sm text-stone-300 italic dark:text-stone-600"
            >
              该评论已被删除
            </p>
            <p
              v-else
              class="mt-2 whitespace-pre-line text-sm leading-relaxed text-stone-700 dark:text-stone-300"
            >
              {{ comment.content }}
            </p>

            <div class="mt-2 flex items-center gap-4 text-xs">
              <button
                v-if="!comment.is_deleted && isLoggedIn"
                type="button"
                class="text-stone-400 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-200"
                @click="startReply(comment)"
              >
                回复
              </button>
              <button
                v-if="canDelete(comment) && !comment.is_deleted"
                type="button"
                class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                @click="remove(comment)"
              >
                删除
              </button>
              <button
                v-if="comment.children_total > 0"
                type="button"
                class="text-stone-400 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-200"
                @click="toggleReplies(comment)"
              >
                {{ expanded[comment.id] ? '收起回复' : `${comment.children_total} 条回复` }}
              </button>
            </div>

            <!-- 二级回复：正序，无嵌套 -->
            <ul
              v-if="expanded[comment.id]"
              class="mt-4 space-y-4 border-l border-stone-100 pl-4 dark:border-stone-800"
            >
              <li
                v-if="replyLoading[comment.id]"
                class="text-xs text-stone-400"
              >
                加载中…
              </li>
              <li
                v-for="reply in replies[comment.id] ?? []"
                :key="reply.id"
                class="flex gap-2.5"
              >
                <img
                  v-if="reply.avatar_url"
                  :src="reply.avatar_url"
                  :alt="reply.user_name"
                  class="size-6 shrink-0 rounded-full object-cover"
                >
                <div
                  v-else
                  class="flex size-6 shrink-0 items-center justify-center rounded-full bg-stone-100 text-[10px] text-stone-400 dark:bg-stone-800"
                >
                  {{ reply.is_deleted ? '?' : reply.user_name.slice(0, 1) }}
                </div>

                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline gap-2">
                    <span class="text-xs font-medium text-stone-600 dark:text-stone-400">
                      {{ reply.is_deleted ? '已注销用户' : reply.user_name }}
                    </span>
                    <span
                      v-if="reply.reply_to_name"
                      class="text-xs text-stone-300 dark:text-stone-600"
                    >
                      回复 {{ reply.reply_to_name }}
                    </span>
                    <time class="text-xs text-stone-300 dark:text-stone-600">
                      {{ formatRelative(reply.created_at) }}
                    </time>
                  </div>

                  <p
                    v-if="reply.is_deleted"
                    class="mt-1 text-xs text-stone-300 italic dark:text-stone-600"
                  >
                    该评论已被删除
                  </p>
                  <p
                    v-else
                    class="mt-1 whitespace-pre-line text-xs leading-relaxed text-stone-600 dark:text-stone-400"
                  >
                    {{ reply.content }}
                  </p>

                  <div class="mt-1 flex items-center gap-3 text-xs">
                    <button
                      v-if="!reply.is_deleted && isLoggedIn"
                      type="button"
                      class="text-stone-400 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-200"
                      @click="startReply(comment)"
                    >
                      回复
                    </button>
                    <button
                      v-if="canDelete(reply) && !reply.is_deleted"
                      type="button"
                      class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                      @click="remove(reply)"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </li>
    </ul>

    <!-- 加载更多 -->
    <button
      v-if="remaining > 0"
      type="button"
      class="mt-10 w-full rounded-md border border-stone-200 py-2.5 text-xs text-stone-500
             transition-colors hover:border-stone-400 hover:text-stone-900
             dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
      @click="load()"
    >
      加载更多（还有 {{ remaining }} 条）
    </button>
  </section>
</template>
