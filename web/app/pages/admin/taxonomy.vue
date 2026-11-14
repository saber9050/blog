<script setup lang="ts">
import type { AdminTaxonomy, PageResult } from '~/types/api'

/**
 * 分类与标签管理。
 *
 * 两个实体的字段和操作完全一样，做成一个页面两个 Tab，
 * 不复制两份几乎相同的代码。后端路径只差一段，用 computed 拼出来。
 *
 * 分区布局和用户 / AI 模型页保持一致：
 * 右上角「新建」按钮展开表单，筛选条单独一行，两者不挤在一起 ——
 * 之前把「输入名称 + 添加」直接摆在筛选位，看起来像在搜索框里新建。
 *
 * 编辑用行内输入而不是弹窗：字段只有「名称」和「状态」两个，
 * 为一个下拉框弹一层遮罩不值得。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

type Kind = 'categories' | 'tags'

const api = useApi()
const { confirm } = useConfirm()

const kind = ref<Kind>('categories')
const items = ref<AdminTaxonomy[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')

/** 新建面板（右上角按钮展开） */
const showCreate = ref(false)
const newName = ref('')
const newStatus = ref(1)
const creating = ref(false)

/** 筛选条件 */
const keyword = ref('')
const filterStatus = ref<'' | 0 | 1>('')

/** 行内编辑 */
const editingId = ref<number | null>(null)
const editName = ref('')
const editStatus = ref(1)
const savingId = ref<number | null>(null)

const kindLabel = computed(() => (kind.value === 'categories' ? '分类' : '标签'))
const basePath = computed(() => `/admin/${kind.value}`)

/** 空列表的文案：区分「一条都没有」和「筛选没命中」，否则用户会以为数据丢了。 */
const emptyText = computed(() => {
  const filtered = keyword.value.trim() !== '' || filterStatus.value !== ''
  return filtered ? `没有匹配的${kindLabel.value}` : `还没有${kindLabel.value}`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (keyword.value.trim()) query.keyword = keyword.value.trim()
    if (filterStatus.value !== '') query.status = filterStatus.value

    const res = await api.request<PageResult<AdminTaxonomy>>(basePath.value, { query })
    items.value = res.list
    total.value = res.total
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 任一筛选条件变化都回第一页，否则会停在超出范围的页码上。 */
function applyFilter() {
  page.value = 1
  load()
}

function goPage(next: number) {
  page.value = next
  load()
}

/** 改每页条数要回到第 1 页，否则可能落在空页上。 */
function onPageSize(size: number) {
  pageSize.value = size
  page.value = 1
  load()
}

async function create() {
  if (creating.value) return
  const name = newName.value.trim()
  if (!name) {
    error.value = `请填写${kindLabel.value}名称`
    return
  }

  creating.value = true
  error.value = ''
  try {
    await api.request(basePath.value, {
      method: 'POST',
      body: { name, status: newStatus.value }
    })
    newName.value = ''
    newStatus.value = 1
    showCreate.value = false
    // 新建的排在最前（后端按创建时间倒序），回第 1 页才看得见
    page.value = 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '创建失败'
  } finally {
    creating.value = false
  }
}

function startEdit(item: AdminTaxonomy) {
  editingId.value = item.id
  editName.value = item.name
  editStatus.value = item.status
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(item: AdminTaxonomy) {
  if (savingId.value) return
  const name = editName.value.trim()
  if (!name) {
    error.value = '名称不能为空'
    return
  }

  savingId.value = item.id
  error.value = ''
  try {
    await api.request(`${basePath.value}/${item.id}`, {
      method: 'PUT',
      body: { name, status: editStatus.value }
    })
    editingId.value = null
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '保存失败'
  } finally {
    savingId.value = null
  }
}

async function remove(item: AdminTaxonomy) {
  const isCategory = kind.value === 'categories'
  const ok = await confirm({
    title: `删除${isCategory ? '分类' : '标签'}「${item.name}」？`,
    description: isCategory
      ? '分类下还有文章时会被拒绝，需要先把文章移到别的分类。'
      : '会同时解除它与所有文章的关联，文章本身不受影响。',
    confirmText: '删除',
    danger: true
  })
  if (!ok) return

  error.value = ''
  try {
    await api.request(`${basePath.value}/${item.id}`, { method: 'DELETE' })
    // 删完当前页最后一条时回退一页，避免停在空页
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

/**
 * 切 Tab 时把编辑态、新建面板、筛选条件、页码全部清掉。
 * 不清的话会出现「在分类里搜了关键词，切到标签还带着」这种串味。
 */
watch(kind, () => {
  editingId.value = null
  showCreate.value = false
  newName.value = ''
  newStatus.value = 1
  keyword.value = ''
  filterStatus.value = ''
  error.value = ''
  page.value = 1
  load()
})

onMounted(load)
</script>

<template>
  <div class="admin-shell">
    <!-- 头部：标题在左，新建按钮在右（与用户 / AI 模型页一致） -->
    <div class="flex shrink-0 items-start justify-between gap-4">
      <div>
        <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
          分类与标签
        </h1>
        <p class="mt-1 text-xs text-stone-400 dark:text-stone-500">
          分类下有文章时不允许删除；标签可以删除，关联会一并清理。
        </p>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
               transition-opacity hover:opacity-90 dark:bg-stone-100 dark:text-stone-900"
        @click="showCreate = !showCreate"
      >
        {{ showCreate ? '收起' : `新建${kindLabel}` }}
      </button>
    </div>

    <!-- Tab -->
    <div class="mt-6 flex shrink-0 gap-6 border-b border-stone-200 dark:border-stone-800">
      <button
        v-for="tab in [
          { key: 'categories', label: '分类' },
          { key: 'tags', label: '标签' }
        ]"
        :key="tab.key"
        type="button"
        class="-mb-px border-b pb-2.5 text-sm transition-colors"
        :class="kind === tab.key
          ? 'border-stone-900 text-stone-900 dark:border-stone-100 dark:text-stone-100'
          : 'border-transparent text-stone-400 hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300'"
        @click="kind = tab.key as Kind"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 新建面板：收起时不占高度，也不和筛选条抢位置 -->
    <div
      v-if="showCreate"
      class="mt-6 shrink-0 rounded-lg border border-stone-200 p-4 dark:border-stone-800"
    >
      <div class="grid gap-3 sm:grid-cols-2">
        <input
          v-model="newName"
          type="text"
          :maxlength="kind === 'categories' ? 50 : 100"
          :placeholder="`${kindLabel}名称`"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs outline-none
                 transition-colors placeholder:text-stone-300 focus:border-stone-400
                 dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
                 dark:focus:border-stone-600"
          @keyup.enter="create"
        >
        <select
          v-model="newStatus"
          class="rounded-md border border-stone-200 bg-transparent px-3 py-1.5 text-xs
                 text-stone-600 outline-none dark:border-stone-800 dark:text-stone-400"
        >
          <option :value="1">
            启用
          </option>
          <option :value="0">
            禁用
          </option>
        </select>
      </div>

      <div class="mt-4 flex items-center gap-3">
        <button
          type="button"
          :disabled="creating"
          class="rounded-md bg-stone-900 px-4 py-1.5 text-xs font-medium text-white
                 transition-opacity hover:opacity-90 disabled:opacity-50
                 dark:bg-stone-100 dark:text-stone-900"
          @click="create"
        >
          {{ creating ? '添加中…' : '添加' }}
        </button>
        <button
          type="button"
          class="text-xs text-stone-400 transition-colors hover:text-stone-700 dark:hover:text-stone-300"
          @click="showCreate = false"
        >
          取消
        </button>
      </div>
    </div>

    <!-- 筛选：与文章列表同款（输入框 + 状态下拉 + 筛选按钮） -->
    <div class="mt-6 flex shrink-0 flex-wrap items-center gap-3">
      <input
        v-model="keyword"
        type="text"
        :placeholder="`搜索${kindLabel}名称`"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
               dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
               dark:focus:border-stone-600"
        @keyup.enter="applyFilter"
      >
      <select
        v-model="filterStatus"
        class="rounded-md border border-stone-200 bg-transparent px-3 py-1.5 text-xs
               text-stone-600 outline-none dark:border-stone-800 dark:text-stone-400"
        @change="applyFilter"
      >
        <option value="">
          全部状态
        </option>
        <option :value="1">
          启用
        </option>
        <option :value="0">
          禁用
        </option>
      </select>
      <button
        type="button"
        class="shrink-0 rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600
               transition-colors hover:border-stone-400 hover:text-stone-900
               dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        @click="applyFilter"
      >
        筛选
      </button>
    </div>

    <p
      v-if="error"
      class="mt-3 shrink-0 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <!-- 列表：滚动条在这一层，表头吸顶 -->
    <div class="admin-scroll mt-6 rounded-lg border border-stone-200 dark:border-stone-800">
      <table class="w-full text-left text-xs">
        <thead class="text-stone-500 dark:text-stone-400">
          <tr>
            <th class="px-4 py-2.5 font-medium">
              名称
            </th>
            <th class="w-24 px-4 py-2.5 font-medium">
              状态
            </th>
            <th class="w-32 px-4 py-2.5 font-medium">
              创建时间
            </th>
            <th class="w-28 px-4 py-2.5 font-medium">
              操作
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100 dark:divide-stone-800">
          <tr v-if="loading">
            <td
              colspan="4"
              class="px-4 py-10 text-center text-stone-400"
            >
              加载中…
            </td>
          </tr>
          <tr v-else-if="items.length === 0">
            <td
              colspan="4"
              class="px-4 py-10 text-center text-stone-400"
            >
              {{ emptyText }}
            </td>
          </tr>
          <tr
            v-for="item in items"
            v-else
            :key="item.id"
          >
            <!-- 编辑态 -->
            <template v-if="editingId === item.id">
              <td class="px-4 py-2">
                <input
                  v-model="editName"
                  type="text"
                  class="w-full rounded border border-stone-300 px-2 py-1 text-xs outline-none
                         dark:border-stone-700 dark:bg-transparent"
                  @keyup.enter="saveEdit(item)"
                >
              </td>
              <td class="px-4 py-2">
                <select
                  v-model="editStatus"
                  class="rounded border border-stone-300 bg-transparent px-2 py-1 text-xs
                         text-stone-600 outline-none dark:border-stone-700 dark:text-stone-400"
                >
                  <option :value="1">
                    启用
                  </option>
                  <option :value="0">
                    禁用
                  </option>
                </select>
              </td>
              <td class="px-4 py-2 text-stone-400">
                —
              </td>
              <td class="px-4 py-2">
                <div class="flex items-center gap-3">
                  <button
                    type="button"
                    :disabled="savingId === item.id"
                    class="text-stone-700 transition-colors hover:text-stone-900 disabled:opacity-50 dark:text-stone-300"
                    @click="saveEdit(item)"
                  >
                    保存
                  </button>
                  <button
                    type="button"
                    class="text-stone-400 transition-colors hover:text-stone-700"
                    @click="cancelEdit"
                  >
                    取消
                  </button>
                </div>
              </td>
            </template>

            <!-- 展示态 -->
            <template v-else>
              <td class="px-4 py-2.5 text-stone-800 dark:text-stone-200">
                {{ item.name }}
              </td>
              <td class="px-4 py-2.5">
                <span
                  class="rounded-full px-2 py-0.5 text-[11px]"
                  :class="item.status === 1
                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                    : 'bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400'"
                >
                  {{ item.status === 1 ? '启用' : '禁用' }}
                </span>
              </td>
              <td class="px-4 py-2.5 text-stone-400 dark:text-stone-500">
                {{ formatDateShort(item.created_at) }}
              </td>
              <td class="px-4 py-2.5">
                <div class="flex items-center gap-3">
                  <button
                    type="button"
                    class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                    @click="startEdit(item)"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                    @click="remove(item)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </template>
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
  </div>
</template>
