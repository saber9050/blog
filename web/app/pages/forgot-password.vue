<script setup lang="ts">
/**
 * 找回密码。
 *
 * 流程：填邮箱 → 收验证码 → 填验证码和新密码 → 提交。
 *
 * 之所以要做成一个页面而不是两步向导：字段只有四个，一步填完更省事，
 * 而且验证码本身有 5 分钟有效期，用户完全来得及。
 */
definePageMeta({ layout: 'auth' })

const api = useApi()

const email = ref('')
const code = ref('')
const password = ref('')
const ack = ref('')

const countdown = ref(0)
const loading = ref(false)
const error = ref('')
const success = ref(false)

let timer: ReturnType<typeof setInterval> | null = null

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const inputClass = 'w-full border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900 dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100'

function messageOf(err: unknown): string {
  const e = err as { statusMessage?: string, data?: { message?: string } }
  return e.statusMessage || e.data?.message || '操作失败，请重试'
}

/** 与后端一致：11-20 位，仅字母数字，且两者都要有。 */
function passwordRule(pwd: string): string {
  if (!pwd) return '请设置新密码'
  if (pwd.length < 11 || pwd.length > 20) return '密码需 11-20 位'
  if (!/^[A-Za-z0-9]+$/.test(pwd)) return '密码只能包含字母和数字'
  if (!/[A-Za-z]/.test(pwd) || !/\d/.test(pwd)) return '密码必须同时包含字母和数字'
  return ''
}

async function sendCode() {
  error.value = ''
  if (!email.value.trim()) {
    error.value = '请先填写邮箱'
    return
  }
  if (countdown.value > 0) return

  try {
    await api.request('/auth/captcha', {
      method: 'POST',
      body: { email: email.value.trim(), purpose: 'reset_password' }
    })
    countdown.value = 60
    timer = setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0 && timer) {
        clearInterval(timer)
        timer = null
      }
    }, 1000)
  } catch (err) {
    error.value = messageOf(err)
  }
}

async function submit() {
  if (loading.value) return
  error.value = ''

  if (!email.value.trim() || !code.value.trim()) {
    error.value = '请填写邮箱和验证码'
    return
  }
  const rule = passwordRule(password.value)
  if (rule) {
    error.value = rule
    return
  }
  if (password.value !== ack.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    await api.request('/auth/reset_password', {
      method: 'POST',
      body: {
        email: email.value.trim(),
        captcha: code.value.trim(),
        new_password: password.value,
        ack: ack.value
      }
    })
    success.value = true
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    loading.value = false
  }
}

useSeoMeta({ title: '找回密码' })
</script>

<template>
  <div>
    <h1 class="font-serif text-[1.75rem] font-semibold text-stone-900 dark:text-stone-100">
      找回密码
    </h1>
    <p class="mt-2 text-sm text-stone-400 dark:text-stone-500">
      验证码会发到你注册时绑定的邮箱。
    </p>

    <!-- 成功态：直接给下一步，不搞倒计时跳转 -->
    <div
      v-if="success"
      class="mt-10"
    >
      <p class="text-sm text-stone-600 dark:text-stone-400">
        密码已修改。旧设备的登录状态会在 15 分钟内自然失效。
      </p>
      <NuxtLink
        to="/login"
        class="mt-8 block w-full rounded-md bg-stone-900 py-3 text-center text-sm font-medium
               text-white transition-opacity hover:opacity-90 dark:bg-stone-100 dark:text-stone-900"
      >
        去登录
      </NuxtLink>
    </div>

    <form
      v-else
      class="mt-10 space-y-5"
      @submit.prevent="submit"
    >
      <input
        v-model="email"
        type="email"
        autocomplete="email"
        placeholder="注册邮箱"
        :class="inputClass"
      >

      <div class="flex items-end gap-3">
        <input
          v-model="code"
          type="text"
          inputmode="numeric"
          maxlength="6"
          autocomplete="one-time-code"
          placeholder="6 位验证码"
          :class="[inputClass, 'min-w-0 flex-1']"
        >
        <button
          type="button"
          :disabled="countdown > 0"
          class="shrink-0 pb-3 text-xs text-stone-500 transition-colors hover:text-stone-900
                 disabled:cursor-not-allowed disabled:text-stone-300
                 dark:text-stone-400 dark:hover:text-stone-100 dark:disabled:text-stone-600"
          @click="sendCode"
        >
          {{ countdown > 0 ? `${countdown} 秒后重发` : '发送验证码' }}
        </button>
      </div>

      <input
        v-model="password"
        type="password"
        autocomplete="new-password"
        placeholder="新密码（11-20 位，字母+数字）"
        :class="inputClass"
      >

      <input
        v-model="ack"
        type="password"
        autocomplete="new-password"
        placeholder="确认新密码"
        :class="inputClass"
      >

      <p
        v-if="error"
        class="text-xs text-rose-600 dark:text-rose-400"
      >
        {{ error }}
      </p>

      <button
        type="submit"
        :disabled="loading"
        class="mt-2 w-full rounded-md bg-stone-900 py-3 text-sm font-medium text-white
               transition-opacity hover:opacity-90 disabled:opacity-50
               dark:bg-stone-100 dark:text-stone-900"
      >
        {{ loading ? '提交中…' : '修改密码' }}
      </button>
    </form>

    <div
      v-if="!success"
      class="mt-10 flex items-center justify-between text-xs"
    >
      <NuxtLink
        to="/login"
        class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
      >
        返回登录
      </NuxtLink>
      <NuxtLink
        to="/register"
        class="text-stone-400 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-100"
      >
        注册新账号
      </NuxtLink>
    </div>
  </div>
</template>
