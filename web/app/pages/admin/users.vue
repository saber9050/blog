<script setup lang="ts">
import type { AdminUserItem, AdminUserPage } from '~/types/api'

/**
 * 后台用户管理。
 *
 * 两个坑：
 * 1. 列表分页字段是 `pageSize`（驼峰），其他模块都是 `page_size`。照抄契约。
 * 2. 列表只返回 `role_id=0` 的普通用户，管理员不出现在这里。
 *
 * 状态切换用 PUT /admin/users/{id}，请求体只有 status 一个字段。
 */
definePageMeta({ middleware: 'admin', layout: 'admin' })

const api = useApi()
const { confirm } = useConfirm()

const page = ref(1)
const pageSize = ref(10)
const keyword = ref('')
const status = ref<'' | 0 | 1>('')

const list = ref<AdminUserItem[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

/** 新建表单 */
const showCreate = ref(false)
const creating = ref(false)
const form = reactive({
  userName: '',
  account: '',
  password: '',
  status: 1
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query: Record<string, unknown> = { page: page.value, page_size: pageSize.value }
    if (keyword.value.trim()) query.keyword = keyword.value.trim()
    if (status.value !== '') query.status = status.value

    const res = await api.request<AdminUserPage>('/admin/users', { query })
    list.value = res.list
    total.value = res.total
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '加载失败'
  } finally {
    loading.value = false
  }
}

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
  error.value = ''

  if (!form.userName.trim()) {
    error.value = '请填写昵称'
    return
  }
  if (!/^\d{11}$/.test(form.account)) {
    error.value = '账号需是 11 位数字'
    return
  }
  if (!/^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{11,20}$/.test(form.password)) {
    error.value = '密码需 11-20 位，且同时含字母和数字'
    return
  }

  creating.value = true
  try {
    await api.request('/admin/users', {
      method: 'POST',
      body: {
        user_name: form.userName.trim(),
        account: form.account,
        password: form.password,
        status: form.status
      }
    })
    form.userName = ''
    form.account = ''
    form.password = ''
    form.status = 1
    showCreate.value = false
    page.value = 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '创建失败'
  } finally {
    creating.value = false
  }
}

async function toggleStatus(user: AdminUserItem) {
  const next = user.status === 1 ? 0 : 1
  try {
    await api.request(`/admin/users/${user.id}`, {
      method: 'PUT',
      body: { status: next }
    })
    user.status = next
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '操作失败'
  }
}

async function remove(user: AdminUserItem) {
  const ok = await confirm({
    title: `删除用户「${user.user_name}」？`,
    description: '这是软删除：账号无法再登录，但评论等历史数据仍留在库里。',
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
  try {
    await api.request(`/admin/users/${user.id}`, { method: 'DELETE' })
    if (list.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    const e = err as { statusMessage?: string }
    error.value = e.statusMessage || '删除失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-shell">
    <div class="flex shrink-0 items-center justify-between">
      <div>
        <h1 class="font-serif text-xl font-semibold text-stone-900 dark:text-stone-100">
          用户
        </h1>
        <p class="mt-1 text-xs text-stone-400 dark:text-stone-500">
          不含管理员
        </p>
      </div>
      <button
        type="button"
        class="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
               transition-opacity hover:opacity-90 dark:bg-stone-100 dark:text-stone-900"
        @click="showCreate = !showCreate"
      >
        {{ showCreate ? '收起' : '新建用户' }}
      </button>
    </div>

    <!-- 新建表单 -->
    <div
      v-if="showCreate"
      class="mt-6 shrink-0 rounded-lg border border-stone-200 p-4 dark:border-stone-800"
    >
      <div class="grid gap-3 sm:grid-cols-2">
        <input
          v-model="form.userName"
          type="text"
          maxlength="15"
          placeholder="昵称"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs outline-none
                 transition-colors placeholder:text-stone-300 focus:border-stone-400
                 dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
                 dark:focus:border-stone-600"
        >
        <input
          v-model="form.account"
          type="text"
          inputmode="numeric"
          maxlength="11"
          placeholder="账号（11 位数字）"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs outline-none
                 transition-colors placeholder:text-stone-300 focus:border-stone-400
                 dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
                 dark:focus:border-stone-600"
        >
        <input
          v-model="form.password"
          type="password"
          placeholder="密码（11-20 位，字母+数字）"
          class="rounded-md border border-stone-200 px-3 py-1.5 text-xs outline-none
                 transition-colors placeholder:text-stone-300 focus:border-stone-400
                 dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
                 dark:focus:border-stone-600"
        >
        <select
          v-model="form.status"
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
          {{ creating ? '创建中…' : '创建' }}
        </button>
        <button
          type="button"
          class="text-xs text-stone-400 transition-colors hover:text-stone-700"
          @click="showCreate = false"
        >
          取消
        </button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="mt-6 flex shrink-0 flex-wrap items-center gap-3">
      <input
        v-model="keyword"
        type="text"
        placeholder="搜索昵称或账号"
        class="min-w-0 flex-1 rounded-md border border-stone-200 px-3 py-1.5 text-xs
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-400
               dark:border-stone-800 dark:bg-transparent dark:placeholder:text-stone-600
               dark:focus:border-stone-600"
        @keyup.enter="applyFilter"
      >
      <select
        v-model="status"
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
              昵称
            </th>
            <th class="w-32 px-4 py-2.5 font-medium">
              账号
            </th>
            <th class="w-40 px-4 py-2.5 font-medium">
              邮箱
            </th>
            <th class="w-20 px-4 py-2.5 font-medium">
              状态
            </th>
            <th class="w-28 px-4 py-2.5 font-medium">
              注册时间
            </th>
            <th class="w-32 px-4 py-2.5 font-medium">
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
              没有匹配的用户
            </td>
          </tr>
          <tr
            v-for="user in list"
            v-else
            :key="user.id"
          >
            <td class="px-4 py-2.5">
              <div class="flex items-center gap-2">
                <img
                  v-if="user.avatar_url"
                  :src="user.avatar_url"
                  :alt="user.user_name"
                  class="size-6 rounded-full object-cover"
                >
                <span
                  v-else
                  class="flex size-6 items-center justify-center rounded-full bg-stone-100
                         text-[10px] text-stone-400 dark:bg-stone-800 dark:text-stone-500"
                >
                  {{ user.user_name.slice(0, 1) }}
                </span>
                <span class="text-stone-800 dark:text-stone-200">{{ user.user_name }}</span>
              </div>
            </td>
            <td class="px-4 py-2.5 text-stone-500 dark:text-stone-400">
              {{ user.account }}
            </td>
            <td class="px-4 py-2.5 text-stone-400 dark:text-stone-500">
              {{ user.email || '—' }}
            </td>
            <td class="px-4 py-2.5">
              <!-- whitespace-nowrap：不加的话「已禁用」会在窄列里折成两行 -->
              <span
                class="whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]"
                :class="user.status === 1
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                  : 'bg-stone-100 text-stone-500 dark:bg-stone-800 dark:text-stone-400'"
              >
                {{ user.status === 1 ? '正常' : '已禁用' }}
              </span>
            </td>
            <td class="px-4 py-2.5 text-stone-400 dark:text-stone-500">
              {{ formatDateShort(user.created_at) }}
            </td>
            <td class="px-4 py-2.5">
              <div class="flex items-center gap-3">
                <button
                  type="button"
                  class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
                  @click="toggleStatus(user)"
                >
                  {{ user.status === 1 ? '禁用' : '启用' }}
                </button>
                <button
                  type="button"
                  class="text-stone-400 transition-colors hover:text-rose-600 dark:text-stone-500"
                  @click="remove(user)"
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
  </div>
</template>
