<script setup lang="ts">
/**
 * 注册页。
 *
 * 三个字段的校验规则与后端完全一致（改规则时两边要一起改）：
 * - 昵称 1-15 字符，全局唯一
 * - 账号 11 位纯数字，全局唯一
 * - 密码 11-20 位，只允许字母数字，且必须同时含字母和数字
 *
 * 唯一性用失焦检测，不在输入时逐字符请求 —— 那样每敲一个字都要打一次后端。
 */
definePageMeta({ layout: 'auth' })

const api = useApi()

const form = reactive({
  userName: '',
  account: '',
  password: '',
  ack: ''
})

const errors = reactive({
  userName: '',
  account: '',
  password: '',
  ack: ''
})

const loading = ref(false)
const submitError = ref('')
/** 每个字段的查重结果：null = 还没查，true = 可用，false = 已占用 */
const available = reactive<Record<'userName' | 'account', boolean | null>>({
  userName: null,
  account: null
})

/** 与后端 `verifyPassword` 保持一致的规则。 */
function passwordRule(pwd: string): string {
  if (!pwd) return '请设置密码'
  if (pwd.length < 11 || pwd.length > 20) return '密码需 11-20 位'
  if (!/^[A-Za-z0-9]+$/.test(pwd)) return '密码只能包含字母和数字'
  if (!/[A-Za-z]/.test(pwd) || !/\d/.test(pwd)) return '密码必须同时包含字母和数字'
  return ''
}

/** 昵称/账号失焦时查重。 */
async function checkName() {
  const name = form.userName.trim()
  errors.userName = ''
  available.userName = null

  if (!name) {
    errors.userName = '请填写昵称'
    return
  }
  if (name.length > 15) {
    errors.userName = '昵称不能超过 15 个字符'
    return
  }

  try {
    const res = await api.request<{ is_exists: boolean }>('/auth/is_exists_name', {
      query: { user_name: name }
    })
    available.userName = !res.is_exists
    if (res.is_exists) errors.userName = '该昵称已被占用'
  } catch {
    // 查重失败不阻塞注册，提交时后端还会再判一次
  }
}

async function checkAccount() {
  const account = form.account.trim()
  errors.account = ''
  available.account = null

  if (!account) {
    errors.account = '请填写账号'
    return
  }
  if (!/^\d{11}$/.test(account)) {
    errors.account = '账号需是 11 位数字'
    return
  }

  try {
    const res = await api.request<{ is_exists: boolean }>('/auth/is_exists_account', {
      query: { account }
    })
    available.account = !res.is_exists
    if (res.is_exists) errors.account = '该账号已被注册'
  } catch {
    // 同上
  }
}

function checkPassword() {
  errors.password = passwordRule(form.password)
}

function checkAck() {
  if (!form.ack) {
    errors.ack = '请再次输入密码'
  } else if (form.ack !== form.password) {
    errors.ack = '两次输入的密码不一致'
  } else {
    errors.ack = ''
  }
}

async function submit() {
  if (loading.value) return
  submitError.value = ''

  // 提交前把所有规则再跑一遍，避免用户没失焦就直接点按钮
  checkPassword()
  checkAck()
  if (!form.userName.trim()) errors.userName = '请填写昵称'
  if (!/^\d{11}$/.test(form.account.trim())) errors.account = '账号需是 11 位数字'

  if (errors.userName || errors.account || errors.password || errors.ack) return

  loading.value = true
  try {
    await api.request('/auth/register', {
      method: 'POST',
      body: {
        user_name: form.userName.trim(),
        account: form.account.trim(),
        password: form.password,
        ack: form.ack
      }
    })
    // 注册接口不返回 token，必须走一次登录
    await navigateTo('/login')
  } catch (err) {
    const e = err as { statusMessage?: string, data?: { message?: string } }
    submitError.value = e.statusMessage || e.data?.message || '注册失败，请重试'
  } finally {
    loading.value = false
  }
}

const inputClass = 'w-full border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900 dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100'

useSeoMeta({ title: '注册' })
</script>

<template>
  <div>
    <h1 class="font-serif text-[1.75rem] font-semibold text-stone-900 dark:text-stone-100">
      注册
    </h1>
    <p class="mt-2 text-sm text-stone-400 dark:text-stone-500">
      只需要一个昵称和账号。
    </p>

    <form
      class="mt-10 space-y-5"
      @submit.prevent="submit"
    >
      <div>
        <input
          v-model="form.userName"
          type="text"
          maxlength="15"
          autocomplete="nickname"
          placeholder="昵称"
          :class="inputClass"
          @blur="checkName"
        >
        <p
          v-if="errors.userName"
          class="mt-1.5 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ errors.userName }}
        </p>
        <p
          v-else-if="available.userName === true"
          class="mt-1.5 text-xs text-emerald-600 dark:text-emerald-500"
        >
          这个昵称可以用
        </p>
      </div>

      <div>
        <input
          v-model="form.account"
          type="text"
          inputmode="numeric"
          maxlength="11"
          autocomplete="username"
          placeholder="账号（11 位数字）"
          :class="inputClass"
          @blur="checkAccount"
        >
        <p
          v-if="errors.account"
          class="mt-1.5 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ errors.account }}
        </p>
        <p
          v-else-if="available.account === true"
          class="mt-1.5 text-xs text-emerald-600 dark:text-emerald-500"
        >
          这个账号可以用
        </p>
      </div>

      <div>
        <input
          v-model="form.password"
          type="password"
          autocomplete="new-password"
          placeholder="密码（11-20 位，字母+数字）"
          :class="inputClass"
          @blur="checkPassword"
        >
        <p
          v-if="errors.password"
          class="mt-1.5 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ errors.password }}
        </p>
      </div>

      <div>
        <input
          v-model="form.ack"
          type="password"
          autocomplete="new-password"
          placeholder="确认密码"
          :class="inputClass"
          @blur="checkAck"
        >
        <p
          v-if="errors.ack"
          class="mt-1.5 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ errors.ack }}
        </p>
      </div>

      <p
        v-if="submitError"
        class="text-xs text-rose-600 dark:text-rose-400"
      >
        {{ submitError }}
      </p>

      <button
        type="submit"
        :disabled="loading"
        class="mt-2 w-full rounded-md bg-stone-900 py-3 text-sm font-medium text-white
               transition-opacity hover:opacity-90 disabled:opacity-50
               dark:bg-stone-100 dark:text-stone-900"
      >
        {{ loading ? '注册中…' : '注册' }}
      </button>
    </form>

    <div class="mt-10 text-xs">
      <NuxtLink
        to="/login"
        class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
      >
        已有账号，去登录
      </NuxtLink>
    </div>
  </div>
</template>
