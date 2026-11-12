<script setup lang="ts">
import type { AdminTaxonomy, PageResult } from '~/types/api'

/**
 * 分类与标签管理。
 *
 * 两个实体的字段和操作完全一样，做成一个页面两个 Tab，
 * 不复制两份几乎相同的代码。后端路径只差一段，用 computed 拼出来。
 *
 * 编辑用行内输入而不是弹窗：字段只有「名称」和「状态」两个，
 * 为一个下拉框弹一层遮罩不值得。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

type Kind = 'categories' | 'tags'

const api = useApi()

const kind = ref<Kind>('categories')
const items = ref<AdminTaxonomy[]>([])
const loading = ref(false)
const error = ref('')

/** 新建表单 */
const newName = ref('')
const newStatus = ref(1)
const creating = ref(false)

/** 行内编辑 */
const editingId = ref<number | null>(null)
const editName = ref('')
const editStatus = ref(1)
const savingId = ref<number | null>(null)

const kindLabel = computed(() => (kind.value === 'categories' ? '分类' : '标签'))
const basePath = computed(() => `/admin/${kind.value}`)

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 分类/标签数量天然少，一次拉 100 条足够，不做分页
    const res = await api.request<PageResult<AdminTaxonomy>>(basePath.value, {
      query: { page: 1, page_size: 100 }
    })
    items.value = res.list
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
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
  const tip = kind.value === 'categories'
    ? `删除分类「${item.name}」？分类下还有文章时会被拒绝。`
    : `删除标签「${item.name}」？会同时解除它与所有文章的关联。`
  if (!confirm(tip)) return

  error.value = ''
  try {
    await api.request(`${basePath.value}/${item.id}`, { method: 'DELETE' })
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

/** 切 Tab 时清掉编辑态，否则会把上一类的编辑目标带过来。 */
watch(kind, () => {
  editingId.value = null
  newName.value = ''
  error.value = ''
  load()
})

onMounted(load)
</script>

<template>
  <div>
    <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
      分类与标签
    </h1>

    <!-- Tab -->
    <div class="mt-6 flex gap-6 border-b border-stone-200 dark:border-stone-800">
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

    <!-- 新建 -->
    <div class="mt-6 flex items-center gap-3">
      <input
        v-model="newName"
        type="text"
        :maxlength="kind === 'categories' ? 50 : 100"
        :placeholder="`新${kindLabel}名称`"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
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
      <button
        type="button"
        :disabled="creating"
        class="shrink-0 rounded-md bg-stone-900 px-4 py-1.5 text-xs font-medium text-white
               transition-opacity hover:opacity-90 disabled:opacity-50
               dark:bg-stone-100 dark:text-stone-900"
        @click="create"
      >
        {{ creating ? '添加中…' : '添加' }}
      </button>
    </div>

    <p
      v-if="error"
      class="mt-3 text-xs text-rose-600 dark:text-rose-400"
    >
      {{ error }}
    </p>

    <!-- 列表 -->
    <div class="mt-6 overflow-hidden rounded-lg border border-stone-200 dark:border-stone-800">
      <table class="w-full text-left text-xs">
        <thead class="bg-stone-50 text-stone-500 dark:bg-stone-900 dark:text-stone-400">
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
              还没有{{ kindLabel }}
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

    <p class="mt-4 text-[11px] text-stone-400 dark:text-stone-600">
      分类下有文章时不允许删除；标签可以删除，关联会一并清理。
    </p>
  </div>
</template>
