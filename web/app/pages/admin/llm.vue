<script setup lang="ts">
/**
 * AI 模型配置。
 *
 * 两条规则来自后端契约，前端必须配合：
 * 1. **密钥只进不出**：列表只返回 `api_key_masked`，编辑时留空表示沿用原密钥。
 * 2. **新建先测连接**：后端在入库前会真实请求一次模型，失败则拒绝写入，
 *    所以这里的「测试连接」按钮是给用户提前自查用的，不是必经流程。
 *
 * 更新只能改运行参数（超时、max_tokens、温度、状态），
 * base_url / api_key / model 不可改 —— 要换模型请删了重建。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

interface LLMConfig {
  id: number
  base_url: string
  api_key_masked: string
  model: string
  type: number
  timeout_sec: number
  max_tokens: number
  temperature: number
  status: number
  created_at: string
  updated_at: string
}

const api = useApi()
const { confirm } = useConfirm()

/**
 * 列表：接口 `/admin/llm-configs` 不分页，一次返回全部配置。
 * 这里在前端切片做分页，只是为了和别的后台列表长得一样（每页条数可选、
 * 列表内部滚动），不是服务端分页。
 */
const configs = ref<LLMConfig[]>([])
const page = ref(1)
const pageSize = ref(10)
const total = computed(() => configs.value.length)
const list = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return configs.value.slice(start, start + pageSize.value)
})

const loading = ref(false)
const error = ref('')

/** 新建表单 */
const showForm = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ ok: boolean, message: string } | null>(null)

const form = reactive({
  baseUrl: 'https://api.deepseek.com/v1',
  apiKey: '',
  model: 'deepseek-chat',
  timeoutSec: 30,
  maxTokens: 2048,
  temperature: 0.3
})

/** 行内编辑：只允许改这四个 */
const editingId = ref<number | null>(null)
const edit = reactive({ timeoutSec: 30, maxTokens: 2048, temperature: 0.3, status: 1 })

async function load() {
  loading.value = true
  error.value = ''
  try {
    configs.value = await api.request<LLMConfig[]>('/admin/llm-configs')
    // 删到最后一页空了，退一页（客户端分页没有服务端兜底，必须自己处理）
    const lastPage = Math.max(1, Math.ceil(configs.value.length / pageSize.value))
    if (page.value > lastPage) page.value = lastPage
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 客户端分页：切页不需要重新请求，直接改页码即可。 */
function goPage(next: number) {
  page.value = next
}

/** 改每页条数要回到第 1 页，否则可能落在空页上。 */
function onPageSize(size: number) {
  pageSize.value = size
  page.value = 1
}

/** 测试连接：成败都返回 HTTP 200，看 data.ok。 */
async function testConnection() {
  if (testing.value) return
  testResult.value = null
  error.value = ''

  if (!form.baseUrl.trim() || !form.model.trim() || !form.apiKey.trim()) {
    error.value = '请填写 Base URL、模型 ID 和 API Key'
    return
  }

  testing.value = true
  try {
    const res = await api.request<{
      ok: boolean
      latency_ms: number
      error: string | null
    }>('/admin/llm-configs/test', {
      method: 'POST',
      body: {
        base_url: form.baseUrl.trim(),
        api_key: form.apiKey.trim(),
        model: form.model.trim(),
        timeout_sec: form.timeoutSec
      }
    })
    testResult.value = res.ok
      ? { ok: true, message: `连接正常，耗时 ${res.latency_ms} ms` }
      : { ok: false, message: res.error || '连接失败' }
  } catch (err) {
    const e = err as { statusMessage?: string }
    testResult.value = { ok: false, message: e.statusMessage || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function create() {
  if (saving.value) return
  error.value = ''

  if (!form.baseUrl.trim() || !form.model.trim() || !form.apiKey.trim()) {
    error.value = '请填写 Base URL、模型 ID 和 API Key'
    return
  }

  saving.value = true
  try {
    await api.request('/admin/llm-configs', {
      method: 'POST',
      body: {
        base_url: form.baseUrl.trim(),
        api_key: form.apiKey.trim(),
        model: form.model.trim(),
        timeout_sec: form.timeoutSec,
        max_tokens: form.maxTokens,
        temperature: form.temperature,
        status: 1
      }
    })
    form.apiKey = ''
    testResult.value = null
    showForm.value = false
    // 新建的排在最前，回第 1 页才看得见
    page.value = 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '创建失败'
  } finally {
    saving.value = false
  }
}

function startEdit(config: LLMConfig) {
  editingId.value = config.id
  edit.timeoutSec = config.timeout_sec
  edit.maxTokens = config.max_tokens
  edit.temperature = config.temperature
  edit.status = config.status
}

async function saveEdit(config: LLMConfig) {
  error.value = ''
  try {
    await api.request(`/admin/llm-configs/${config.id}`, {
      method: 'PUT',
      body: {
        timeout_sec: edit.timeoutSec,
        max_tokens: edit.maxTokens,
        temperature: edit.temperature,
        status: edit.status
      }
    })
    editingId.value = null
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '保存失败'
  }
}

async function remove(config: LLMConfig) {
  const ok = await confirm({
    title: `删除配置「${config.model}」？`,
    description: '删除后文章摘要生成会失去这个可用模型；已发布的文章不受影响。',
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
  try {
    await api.request(`/admin/llm-configs/${config.id}`, { method: 'DELETE' })
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

const inputClass = 'w-full rounded-md border border-stone-200 px-3 py-1.5 text-xs outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400 dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600 dark:focus:border-stone-600'

onMounted(load)
</script>

<template>
  <div class="admin-shell">
    <div class="flex shrink-0 items-center justify-between">
      <div>
        <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
          AI 模型
        </h1>
        <p class="mt-1 text-xs text-stone-400 dark:text-stone-500">
          用于文章摘要生成，OpenAI 兼容接口。密钥加密存库、接口只返回脱敏串，换模型请删除后重建。
        </p>
      </div>
      <button
        type="button"
        class="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
               transition-opacity hover:opacity-90 dark:bg-stone-100 dark:text-stone-900"
        @click="showForm = !showForm"
      >
        {{ showForm ? '收起' : '新建配置' }}
      </button>
    </div>

    <!-- 新建表单 -->
    <div
      v-if="showForm"
      class="mt-6 shrink-0 rounded-lg border border-stone-200 p-4 dark:border-stone-800"
    >
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="sm:col-span-2">
          <label class="text-[11px] text-stone-400 dark:text-stone-500">Base URL（到 /v1 为止）</label>
          <input
            v-model="form.baseUrl"
            type="text"
            placeholder="https://api.deepseek.com/v1"
            :class="inputClass"
          >
        </div>
        <div>
          <label class="text-[11px] text-stone-400 dark:text-stone-500">模型 ID</label>
          <input
            v-model="form.model"
            type="text"
            placeholder="deepseek-chat"
            :class="inputClass"
          >
        </div>
        <div>
          <label class="text-[11px] text-stone-400 dark:text-stone-500">API Key</label>
          <input
            v-model="form.apiKey"
            type="password"
            placeholder="sk-…"
            :class="inputClass"
          >
        </div>
        <div>
          <label class="text-[11px] text-stone-400 dark:text-stone-500">超时（秒）</label>
          <input
            v-model.number="form.timeoutSec"
            type="number"
            :class="inputClass"
          >
        </div>
        <div>
          <label class="text-[11px] text-stone-400 dark:text-stone-500">max_tokens</label>
          <input
            v-model.number="form.maxTokens"
            type="number"
            :class="inputClass"
          >
        </div>
        <div>
          <label class="text-[11px] text-stone-400 dark:text-stone-500">temperature</label>
          <input
            v-model.number="form.temperature"
            type="number"
            step="0.1"
            min="0"
            max="2"
            :class="inputClass"
          >
        </div>
      </div>

      <div class="mt-4 flex items-center gap-3">
        <button
          type="button"
          :disabled="testing"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
                 transition-colors hover:border-stone-400 hover:text-stone-900 disabled:opacity-50
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
          @click="testConnection"
        >
          {{ testing ? '测试中…' : '测试连接' }}
        </button>
        <button
          type="button"
          :disabled="saving"
          class="rounded-md bg-stone-900 px-4 py-1.5 text-xs font-medium text-white
                 transition-opacity hover:opacity-90 disabled:opacity-50
                 dark:bg-stone-100 dark:text-stone-900"
          @click="create"
        >
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button
          type="button"
          class="text-xs text-stone-400 transition-colors hover:text-stone-700"
          @click="showForm = false"
        >
          取消
        </button>
      </div>

      <p
        v-if="testResult"
        class="mt-3 text-xs"
        :class="testResult.ok ? 'text-emerald-600 dark:text-emerald-500' : 'text-rose-600 dark:text-rose-400'"
      >
        {{ testResult.message }}
      </p>

      <p class="mt-3 text-[11px] text-stone-400 dark:text-stone-600">
        保存前后端会再测一次连接，失败则不入库 —— 这样可以避免库里堆一堆连不通的配置。
      </p>
    </div>

    <p
      v-if="error"
      class="mt-4 shrink-0 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <!-- 列表：滚动条在这一层，表头吸顶 -->
    <div class="admin-scroll mt-6 rounded-lg border border-stone-200 dark:border-stone-800">
      <table class="w-full text-left text-xs">
        <thead class="text-stone-500 dark:text-stone-400">
          <tr>
            <th class="px-4 py-2.5 font-medium">
              模型
            </th>
            <th class="px-4 py-2.5 font-medium">
              Base URL
            </th>
            <th class="w-32 px-4 py-2.5 font-medium">
              密钥
            </th>
            <th class="w-52 px-4 py-2.5 font-medium">
              运行参数
            </th>
            <th class="w-24 px-4 py-2.5 font-medium">
              状态
            </th>
            <th class="w-28 px-4 py-2.5 font-medium">
              操作
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100 dark:divide-stone-800">
          <tr v-if="loading">
            <td
              colspan="6"
              class="px-4 py-10 text-center text-stone-400"
            >
              加载中…
            </td>
          </tr>
          <tr v-else-if="list.length === 0">
            <td
              colspan="6"
              class="px-4 py-10 text-center text-stone-400"
            >
              还没有配置，添加一条才能用 AI 摘要
            </td>
          </tr>
          <tr
            v-for="config in list"
            v-else
            :key="config.id"
          >
            <td class="px-4 py-2.5 text-stone-800 dark:text-stone-200">
              {{ config.model }}
            </td>
            <td class="px-4 py-2.5 text-stone-500 dark:text-stone-400">
              {{ config.base_url }}
            </td>
            <td class="px-4 py-2.5 font-mono text-stone-400 dark:text-stone-500">
              {{ config.api_key_masked }}
            </td>
            <!--
              参数列：编辑时每个输入框前面带标签，光三个数字框没人知道哪个是哪个。
              值是「超时 / 上限 / 温度」，对应 config.yaml 里的
              timeout_sec / max_tokens / temperature。
            -->
            <td class="px-4 py-2.5 text-stone-400 dark:text-stone-500">
              <div
                v-if="editingId === config.id"
                class="flex flex-col gap-1.5"
              >
                <label class="flex items-center gap-2">
                  <span class="w-11 shrink-0 text-[11px] text-stone-500 dark:text-stone-400">超时</span>
                  <input
                    v-model.number="edit.timeoutSec"
                    type="number"
                    min="1"
                    class="w-14 rounded border border-stone-300 px-1 py-0.5 text-[11px]
                           dark:border-stone-700 dark:bg-transparent"
                  >
                  <span class="text-[11px]">秒</span>
                </label>
                <label class="flex items-center gap-2">
                  <span class="w-11 shrink-0 text-[11px] text-stone-500 dark:text-stone-400">上限</span>
                  <input
                    v-model.number="edit.maxTokens"
                    type="number"
                    min="1"
                    class="w-14 rounded border border-stone-300 px-1 py-0.5 text-[11px]
                           dark:border-stone-700 dark:bg-transparent"
                  >
                  <span class="text-[11px]">token</span>
                </label>
                <label class="flex items-center gap-2">
                  <span class="w-11 shrink-0 text-[11px] text-stone-500 dark:text-stone-400">温度</span>
                  <input
                    v-model.number="edit.temperature"
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    class="w-14 rounded border border-stone-300 px-1 py-0.5 text-[11px]
                           dark:border-stone-700 dark:bg-transparent"
                  >
                  <span class="text-[11px]">0–2</span>
                </label>
              </div>

              <!-- 展示态同样带字段名，别只给「30s / 2048 / 0.3」 -->
              <div
                v-else
                class="space-y-0.5 text-[11px] leading-relaxed"
              >
                <div>超时 {{ config.timeout_sec }} 秒</div>
                <div>上限 {{ config.max_tokens }} token</div>
                <div>温度 {{ config.temperature }}</div>
              </div>
            </td>

            <!-- 状态在编辑态可以改：禁用只是「不参与摘要生成」，不是删除 -->
            <td class="px-4 py-2.5">
              <select
                v-if="editingId === config.id"
                v-model.number="edit.status"
                class="rounded border border-stone-300 bg-transparent px-1 py-0.5 pr-5 text-[11px]
                       text-stone-600 outline-none dark:border-stone-700 dark:text-stone-300"
              >
                <option :value="1">
                  启用
                </option>
                <option :value="0">
                  禁用
                </option>
              </select>
              <span
                v-else
                class="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]"
                :class="config.status === 1
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                  : 'bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400'"
              >
                {{ config.status === 1 ? '启用' : '禁用' }}
              </span>
            </td>
            <td class="px-4 py-2.5">
              <div
                v-if="editingId === config.id"
                class="flex items-center gap-2"
              >
                <button
                  type="button"
                  class="text-stone-700 transition-colors hover:text-stone-900 dark:text-stone-300"
                  @click="saveEdit(config)"
                >
                  保存
                </button>
                <button
                  type="button"
                  class="text-stone-400 transition-colors hover:text-stone-700"
                  @click="editingId = null"
                >
                  取消
                </button>
              </div>
              <div
                v-else
                class="flex items-center gap-3"
              >
                <button
                  type="button"
                  class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                  @click="startEdit(config)"
                >
                  编辑
                </button>
                <button
                  type="button"
                  class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                  @click="remove(config)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <AdminPager
      class="mt-4"
      :page="page"
      :total="total"
      :page-size="pageSize"
      @update:page="goPage"
      @update:page-size="onPageSize"
    />

    <!--
      参数说明常驻在列表下方：编辑时才解释太晚，而这三个词本身不自明。
      措辞用「调大 / 调小」这种可操作的表述，不抄厂商文档的抽象定义。
    -->
    <dl class="mt-3 grid shrink-0 gap-x-6 gap-y-1 text-[11px] leading-relaxed text-stone-400 sm:grid-cols-3 dark:text-stone-500">
      <div>
        <dt class="inline text-stone-600 dark:text-stone-300">
          超时
        </dt>
        <dd class="inline">
          单次请求最多等多久。走代理或网络慢就调大，默认 30 秒。
        </dd>
      </div>
      <div>
        <dt class="inline text-stone-600 dark:text-stone-300">
          上限
        </dt>
        <dd class="inline">
          生成摘要的最大长度（token）。中文摘要三四百字用 1024 就够，2048 更保险。
        </dd>
      </div>
      <div>
        <dt class="inline text-stone-600 dark:text-stone-300">
          温度
        </dt>
        <dd class="inline">
          0–2，越低越稳定。摘要用 0.2–0.4；调到 1 以上容易跑偏、胡说。
        </dd>
      </div>
    </dl>
  </div>
</template>
