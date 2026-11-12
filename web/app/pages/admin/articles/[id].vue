<script setup lang="ts">
import { marked } from 'marked'
import type { Article, Taxonomy } from '~/types/api'

/**
 * 文章编辑器。新建与编辑共用一个页面：
 *
 * - `/admin/articles/new` → 新建
 * - `/admin/articles/{id}` → 编辑
 *
 * 编辑时用前台详情接口取 `content` —— 后台没有单独的详情接口。
 * 副作用是每打开一次编辑页浏览量 +1，这是后端现状，前端无法绕过。
 *
 * 正文用 textarea 而不是引入 Markdown 编辑器组件：这个项目只有一个人写文章，
 * 双栏实时预览足够；引一个 300KB 的编辑器换来的收益不抵它的维护成本。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

const route = useRoute()
const api = useApi()

const articleId = computed(() => String(route.params.id))
const isNew = computed(() => articleId.value === 'new')

const form = reactive({
  title: '',
  typeId: null as number | null,
  tagIds: [] as number[],
  coverUrl: '',
  summary: '',
  content: '',
  status: 0
})

const categories = ref<Taxonomy[]>([])
const tags = ref<Taxonomy[]>([])

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const savedMsg = ref('')

const preview = ref(false)
const generating = ref(false)
const summaryErr = ref('')

/** 预览用：与服务端详情页同一套 marked 配置，避免预览和线上不一样。 */
const previewHtml = computed(() => {
  if (!form.content) return '<p class="text-stone-400">还没有内容</p>'
  return marked.parse(form.content, { async: false, gfm: true, breaks: true }) as string
})

// ---------------------------------------------------------------
// 编辑器工具条
// ---------------------------------------------------------------

const contentRef = ref<HTMLTextAreaElement | null>(null)
const coverInput = ref<HTMLInputElement | null>(null)
const imageInput = ref<HTMLInputElement | null>(null)

const uploadingCover = ref(false)
const uploadingImage = ref(false)
const uploadErr = ref('')

/**
 * 用文本替换当前选区，并把光标放到合适位置。
 *
 * @param replacement 替换后的完整文本
 * @param selectFrom 相对选区起点的选中开始偏移（用于让用户接着输入）
 * @param selectTo 选中结束偏移
 */
function replaceSelection(replacement: string, selectFrom?: number, selectTo?: number) {
  const el = contentRef.value
  if (!el) {
    form.content += replacement
    return
  }

  const start = el.selectionStart
  const end = el.selectionEnd
  form.content = form.content.slice(0, start) + replacement + form.content.slice(end)

  nextTick(() => {
    el.focus()
    const from = start + (selectFrom ?? replacement.length)
    const to = start + (selectTo ?? replacement.length)
    el.setSelectionRange(from, to)
  })
}

/**
 * 用前后缀包住选中文本（加粗、链接等）。没有选中时插入占位词并选中它，
 * 用户可以直接打字覆盖，不用手动删占位符。
 */
function wrapSelection(before: string, after: string, placeholder: string) {
  const el = contentRef.value
  if (!el) {
    form.content += before + placeholder + after
    return
  }

  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = form.content.slice(start, end) || placeholder
  const replacement = before + selected + after
  form.content = form.content.slice(0, start) + replacement + form.content.slice(end)

  nextTick(() => {
    el.focus()
    el.setSelectionRange(start + before.length, start + before.length + selected.length)
  })
}

/** 在光标所在行的行首加前缀（标题、引用）。 */
function prefixLine(prefix: string) {
  const el = contentRef.value
  if (!el) {
    form.content += prefix
    return
  }

  const start = el.selectionStart
  // 找到当前行的起点
  const lineStart = form.content.lastIndexOf('\n', start - 1) + 1
  form.content = form.content.slice(0, lineStart) + prefix + form.content.slice(lineStart)

  nextTick(() => {
    el.focus()
    el.setSelectionRange(start + prefix.length, start + prefix.length)
  })
}

/**
 * 插入代码块。选中了多行时把它们整体包进围栏，
 * 否则插一个空围栏并把光标放在中间，直接就能敲代码。
 */
function insertCodeBlock() {
  const el = contentRef.value
  if (!el) {
    form.content += '\n```\n\n```\n'
    return
  }

  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = form.content.slice(start, end)

  if (selected) {
    const replacement = '```\n' + selected + '\n```'
    replaceSelection(replacement)
    return
  }

  const replacement = '```\n\n```'
  replaceSelection(replacement, 4, 4)
}

/** 上传一张图片到后端，返回完整 URL。封面与正文共用这个接口。 */
async function uploadImage(file: File): Promise<string | null> {
  if (file.size > 10 * 1024 * 1024) {
    uploadErr.value = '图片不能超过 10MB'
    return null
  }

  const body = new FormData()
  body.append('file', file)
  const res = await api.request<{ url: string }>('/admin/upload', { method: 'POST', body })
  return res.url
}

/** 选择封面并上传，成功后立即预览。 */
async function onCoverPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  uploadErr.value = ''
  uploadingCover.value = true
  try {
    const url = await uploadImage(file)
    if (url) form.coverUrl = url
  } catch (err) {
    const e = err as { statusMessage?: string }
    uploadErr.value = e.statusMessage || '封面上传失败'
  } finally {
    uploadingCover.value = false
    input.value = ''
  }
}

/** 打开封面上传选择器。 */
function pickCover() {
  coverInput.value?.click()
}

function removeCover() {
  form.coverUrl = ''
}

/** 选择正文图片并插入 Markdown。 */
async function onImagePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  uploadErr.value = ''
  uploadingImage.value = true
  try {
    const url = await uploadImage(file)
    if (url) {
      // 前后各留一个换行，避免图片和相邻段落粘在一起
      const prefix = form.content && !form.content.endsWith('\n') ? '\n' : ''
      replaceSelection(`${prefix}![](${url})\n`)
    }
  } catch (err) {
    const e = err as { statusMessage?: string }
    uploadErr.value = e.statusMessage || '图片上传失败'
  } finally {
    uploadingImage.value = false
    input.value = ''
  }
}

/** 打开正文图片选择器。 */
function pickImage() {
  imageInput.value?.click()
}

/**
 * 工具条配置。
 *
 * 只放最常用的几个：加粗、标题、引用、链接、代码块、图片。
 * 再多就成了半成品编辑器，不如直接写 Markdown 快。
 */
const toolbar = [
  { key: 'bold', icon: 'i-lucide-bold', title: '加粗', action: () => wrapSelection('**', '**', '粗体') },
  { key: 'heading', icon: 'i-lucide-heading-2', title: '二级标题', action: () => prefixLine('## ') },
  { key: 'quote', icon: 'i-lucide-quote', title: '引用', action: () => prefixLine('> ') },
  { key: 'link', icon: 'i-lucide-link', title: '链接', action: () => wrapSelection('[', '](https://)', '链接文字') },
  { key: 'code', icon: 'i-lucide-code', title: '代码块', action: insertCodeBlock },
  { key: 'image', icon: 'i-lucide-image', title: '插入图片', action: pickImage }
]

async function loadOptions() {
  try {
    const [cats, tgs] = await Promise.all([
      api.request<Taxonomy[]>('/categories'),
      api.request<Taxonomy[]>('/tags')
    ])
    categories.value = cats
    tags.value = tgs
    if (isNew.value && !form.typeId) form.typeId = cats[0]?.id ?? null
  } catch {
    // 分类/标签拉不到时不影响正文编辑，保存时后端会报明确错误
  }
}

async function loadArticle() {
  if (isNew.value) return
  loading.value = true
  try {
    const data = await api.request<Article>(`/articles/${articleId.value}`)
    form.title = data.title
    form.typeId = data.category?.id ?? null
    form.tagIds = data.tags.map(t => t.id)
    form.coverUrl = data.cover_url
    form.summary = data.summary
    form.content = data.content ?? ''
    form.status = data.status
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '文章不存在'
  } finally {
    loading.value = false
  }
}

/** 用当前配置的模型生成摘要，结果填进输入框，不落库。 */
async function generateSummary() {
  if (generating.value) return
  summaryErr.value = ''

  if (!form.title.trim() || !form.content.trim()) {
    summaryErr.value = '先写标题和正文'
    return
  }

  generating.value = true
  try {
    // 摘要接口需要指定用哪条模型配置，取第一条可用的
    const configs = await api.request<Array<{ id: number, status: number }>>('/admin/llm-configs')
    const usable = configs.find(c => c.status === 1)
    if (!usable) {
      summaryErr.value = '还没有可用的模型配置，去「AI 模型」里加一条'
      return
    }
    const res = await api.request<{ summary: string }>('/admin/articles/generate-summary', {
      method: 'POST',
      body: {
        config_id: usable.id,
        title: form.title,
        content: form.content
      }
    })
    form.summary = res.summary
  } catch (err) {
    const e = err as { statusMessage?: string }
    summaryErr.value = e.statusMessage || '生成失败'
  } finally {
    generating.value = false
  }
}

function toggleTag(tagId: number) {
  const index = form.tagIds.indexOf(tagId)
  if (index >= 0) form.tagIds.splice(index, 1)
  else form.tagIds.push(tagId)
}

async function save(status?: number) {
  if (saving.value) return
  error.value = ''
  savedMsg.value = ''

  if (!form.title.trim()) {
    error.value = '标题不能为空'
    return
  }
  if (!form.content.trim()) {
    error.value = '正文不能为空'
    return
  }
  if (!form.typeId) {
    error.value = '请选择分类'
    return
  }

  if (status !== undefined) form.status = status

  saving.value = true
  try {
    const body = {
      title: form.title.trim(),
      type_id: form.typeId,
      tag_ids: form.tagIds,
      cover_url: form.coverUrl.trim(),
      summary: form.summary.trim(),
      content: form.content,
      status: form.status
    }

    if (isNew.value) {
      const res = await api.request<{ id: number }>('/admin/articles', {
        method: 'POST',
        body
      })
      // 建完立刻切到编辑态，避免用户再点一次保存时重复创建
      await navigateTo(`/admin/articles/${res.id}`, { replace: true })
    } else {
      await api.request(`/admin/articles/${articleId.value}`, { method: 'PUT', body })
      savedMsg.value = '已保存'
    }
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (isNew.value) return
  if (!confirm('确定删除这篇文章？评论与图片会一并清理，不可恢复。')) return
  try {
    await api.request(`/admin/articles/${articleId.value}`, { method: 'DELETE' })
    await navigateTo('/admin/articles')
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

onMounted(async () => {
  await loadOptions()
  await loadArticle()
})
</script>

<template>
  <div>
    <!-- 顶栏 -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <NuxtLink
          to="/admin/articles"
          class="text-xs text-stone-400 transition-colors hover:text-stone-900 dark:hover:text-stone-100"
        >
          ← 文章
        </NuxtLink>
        <span class="text-xs text-stone-300 dark:text-stone-700">/</span>
        <h1 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
          {{ isNew ? '写文章' : '编辑文章' }}
        </h1>
      </div>

      <div class="flex items-center gap-3">
        <span
          v-if="savedMsg"
          class="text-xs text-emerald-600 dark:text-emerald-500"
        >
          {{ savedMsg }}
        </span>
        <button
          v-if="!isNew"
          type="button"
          class="text-xs text-stone-400 transition-colors hover:text-rose-600"
          @click="remove"
        >
          删除
        </button>
        <button
          type="button"
          :disabled="saving"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
                 transition-colors hover:border-stone-400 hover:text-stone-900 disabled:opacity-50
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
          @click="save(0)"
        >
          存草稿
        </button>
        <button
          type="button"
          :disabled="saving"
          class="rounded-md bg-stone-900 px-4 py-1.5 text-xs font-medium text-white
                 transition-opacity hover:opacity-90 disabled:opacity-50
                 dark:bg-stone-100 dark:text-stone-900"
          @click="save(1)"
        >
          {{ saving ? '保存中…' : '发布' }}
        </button>
      </div>
    </div>

    <p
      v-if="error"
      class="mt-4 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <div
      v-if="loading"
      class="mt-10 text-xs text-stone-400"
    >
      加载中…
    </div>

    <!--
      双栏用 main.css 里的 .editor-split（原生媒体查询）而不是 lg:flex-row：
      本项目里 Tailwind 的响应式类在窄屏下会和 w-full 抢宽度，
      侧栏 shrink-0 + 100% 宽会把主区压成一条缝。原生 CSS 行为确定。
    -->
    <div
      v-else
      class="editor-split mt-8"
    >
      <!-- 主区：标题 + 正文 -->
      <div class="editor-main">
        <input
          v-model="form.title"
          type="text"
          maxlength="200"
          placeholder="标题"
          class="w-full border-b border-stone-200 bg-transparent pb-3 font-serif text-2xl font-semibold
                 text-stone-900 outline-none transition-colors placeholder:text-stone-300
                 focus:border-stone-900 dark:border-stone-800 dark:text-stone-100
                 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
        >

        <!-- 编辑 / 预览切换 + 工具条 -->
        <div class="mt-6 flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 pb-2 dark:border-stone-800">
          <div class="flex items-center gap-4">
            <div class="flex gap-4 text-xs">
              <button
                type="button"
                class="transition-colors"
                :class="!preview ? 'text-stone-900 dark:text-stone-100' : 'text-stone-400 hover:text-stone-600 dark:hover:text-stone-300'"
                @click="preview = false"
              >
                编辑
              </button>
              <button
                type="button"
                class="transition-colors"
                :class="preview ? 'text-stone-900 dark:text-stone-100' : 'text-stone-400 hover:text-stone-600 dark:hover:text-stone-300'"
                @click="preview = true"
              >
                预览
              </button>
            </div>

            <!-- 工具条只在编辑态出现：预览态点它没有意义 -->
            <div
              v-if="!preview"
              class="flex items-center gap-0.5 border-l border-stone-200 pl-3 dark:border-stone-800"
            >
              <button
                v-for="tool in toolbar"
                :key="tool.key"
                :data-tool="tool.key"
                type="button"
                class="rounded p-1.5 text-stone-400 transition-colors hover:bg-stone-100
                       hover:text-stone-900 disabled:opacity-40 dark:hover:bg-stone-800 dark:hover:text-stone-100"
                :title="tool.title"
                :disabled="uploadingImage"
                @click="tool.action()"
              >
                <UIcon
                  :name="tool.icon"
                  class="size-3.5"
                />
              </button>
              <span
                v-if="uploadingImage"
                class="ml-1 text-[11px] text-stone-400"
              >
                上传中…
              </span>
            </div>
          </div>

          <span class="text-[11px] text-stone-300 dark:text-stone-600">
            {{ form.content.length }} 字符
          </span>
        </div>

        <!-- 正文图片的隐藏选择器 -->
        <input
          id="body-image-input"
          ref="imageInput"
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          class="hidden"
          @change="onImagePicked"
        >

        <p
          v-if="uploadErr"
          class="mt-2 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ uploadErr }}
        </p>

        <!-- 高度给足：写长文时编辑区太矮会不停滚动 -->
        <textarea
          v-if="!preview"
          ref="contentRef"
          v-model="form.content"
          placeholder="用 Markdown 写正文…（工具条可插入图片与代码块）"
          class="mt-4 h-[60vh] min-h-[420px] w-full resize-y rounded-md border border-stone-200
                 bg-transparent p-4 font-mono text-[13px] leading-relaxed text-stone-800
                 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
                 dark:border-stone-800 dark:text-stone-200 dark:placeholder:text-stone-600
                 dark:focus:border-stone-600"
        />

        <!-- 预览区复用正文排版样式 -->
        <!-- eslint-disable vue/no-v-html, better-tailwindcss/no-unknown-classes -->
        <div
          v-else
          class="article-body mt-4 rounded-md border border-stone-200 p-6 dark:border-stone-800"
          v-html="previewHtml"
        />
        <!-- eslint-enable vue/no-v-html, better-tailwindcss/no-unknown-classes -->
      </div>

      <!-- 侧栏：分类 / 标签 / 摘要 / 封面 -->
      <aside class="editor-aside space-y-6">
        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">分类</label>
          <select
            v-model="form.typeId"
            class="mt-2 w-full rounded-md border border-stone-200 bg-transparent px-3 py-2 text-xs
                   text-stone-700 outline-none dark:border-stone-800 dark:text-stone-300"
          >
            <option
              :value="null"
              disabled
            >
              请选择
            </option>
            <option
              v-for="cat in categories"
              :key="cat.id"
              :value="cat.id"
            >
              {{ cat.name }}
            </option>
          </select>
        </div>

        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">标签</label>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="tag in tags"
              :key="tag.id"
              type="button"
              class="rounded-full border px-2.5 py-1 text-[11px] transition-colors"
              :class="form.tagIds.includes(tag.id)
                ? 'border-stone-900 bg-stone-900 text-white dark:border-stone-100 dark:bg-stone-100 dark:text-stone-900'
                : 'border-stone-200 text-stone-500 hover:border-stone-400 dark:border-stone-800 dark:text-stone-400'"
              @click="toggleTag(tag.id)"
            >
              {{ tag.name }}
            </button>
            <p
              v-if="tags.length === 0"
              class="text-[11px] text-stone-400"
            >
              还没有标签
            </p>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between">
            <label class="text-xs text-stone-400 dark:text-stone-500">摘要</label>
            <button
              type="button"
              :disabled="generating"
              class="text-[11px] text-stone-400 transition-colors hover:text-stone-900 disabled:opacity-50 dark:hover:text-stone-100"
              @click="generateSummary"
            >
              {{ generating ? '生成中…' : 'AI 生成' }}
            </button>
          </div>
          <textarea
            v-model="form.summary"
            rows="4"
            maxlength="255"
            placeholder="列表页展示的一句话"
            class="mt-2 w-full resize-none rounded-md border border-stone-200 bg-transparent px-3 py-2
                   text-xs leading-relaxed text-stone-700 outline-none transition-colors
                   placeholder:text-stone-300 focus:border-stone-400 dark:border-stone-800
                   dark:text-stone-300 dark:placeholder:text-stone-600 dark:focus:border-stone-600"
          />
          <p
            v-if="summaryErr"
            class="mt-1 text-[11px] text-rose-600 dark:text-rose-400"
          >
            {{ summaryErr }}
          </p>
        </div>

        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">封面</label>

          <!-- 有封面就显示预览，并把「更换 / 移除」放图下面 -->
          <div
            v-if="form.coverUrl"
            class="mt-2 overflow-hidden rounded-md border border-stone-200 dark:border-stone-800"
          >
            <img
              :src="form.coverUrl"
              alt="封面"
              class="block w-full object-cover"
            >
            <div class="flex items-center justify-between border-t border-stone-100 px-2 py-1.5 dark:border-stone-800">
              <button
                type="button"
                class="text-[11px] text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                :disabled="uploadingCover"
                @click="pickCover"
              >
                {{ uploadingCover ? '上传中…' : '更换' }}
              </button>
              <button
                type="button"
                class="text-[11px] text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                @click="removeCover"
              >
                移除
              </button>
            </div>
          </div>

          <button
            v-else
            type="button"
            class="mt-2 flex w-full flex-col items-center justify-center gap-1.5 rounded-md
                   border border-dashed border-stone-200 py-7 text-[11px] text-stone-400
                   transition-colors hover:border-stone-400 hover:text-stone-600
                   disabled:opacity-60 dark:border-stone-800 dark:hover:border-stone-600
                   dark:hover:text-stone-300"
            :disabled="uploadingCover"
            @click="pickCover"
          >
            <UIcon
              name="i-lucide-image-plus"
              class="size-4"
            />
            {{ uploadingCover ? '上传中…' : '上传封面' }}
          </button>

          <input
            id="cover-input"
            ref="coverInput"
            type="file"
            accept=".jpg,.jpeg,.png,.webp"
            class="hidden"
            @change="onCoverPicked"
          >

          <p class="mt-1.5 text-[11px] text-stone-400 dark:text-stone-600">
            jpg / png / webp，不超过 10MB
          </p>
        </div>

        <div class="rounded-md border border-stone-200 px-3 py-2 dark:border-stone-800">
          <span class="text-[11px] text-stone-400 dark:text-stone-500">当前状态</span>
          <p class="mt-1 text-xs text-stone-700 dark:text-stone-300">
            {{ form.status === 1 ? '已发布' : '草稿' }}
          </p>
        </div>
      </aside>
    </div>
  </div>
</template>
