<script setup lang="ts">
import type { ImageCaptcha } from '~/types/api'

/**
 * 登录页。两种方式并存：
 *
 * - 账号密码 + 图形验证码（主路径）
 * - 邮箱验证码（没记密码时用，也可作为无密码登录）
 *
 * 图形验证码校验失败时后端会删除 key，所以任何一次失败都必须重新拉一张，
 * 否则用户拿着已经作废的验证码重试，永远登不进去。
 */
definePageMeta({ layout: 'auth' })

const route = useRoute()
const { login, loginByEmail, isLoggedIn } = useAuth()
const api = useApi()

const mode = ref<'password' | 'email'>('password')
const loading = ref(false)
const error = ref('')

// ---- 密码登录 ----
const account = ref('')
const password = ref('')
const captchaCode = ref('')
const captcha = ref<ImageCaptcha | null>(null)

// ---- 邮箱登录 ----
const email = ref('')
const emailCode = ref('')
const countdown = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

/** 已登录的人不该停在登录页。 */
onMounted(() => {
  if (isLoggedIn.value) {
    navigateTo(destination())
  }
  loadCaptcha()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

/** 登录成功后的落点：优先回跳，否则回首页。 */
function destination(): string {
  const redirect = route.query.redirect
  return typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/'
}

/** 拉一张新的图形验证码。 */
async function loadCaptcha() {
  try {
    captcha.value = await api.request<ImageCaptcha>('/auth/image_captcha')
    captchaCode.value = ''
  } catch {
    captcha.value = null
  }
}

/** 统一下线：接口错误里的 message 直接展示，比「操作失败」有用得多。 */
function messageOf(err: unknown): string {
  const e = err as { statusMessage?: string, data?: { message?: string } }
  return e.statusMessage || e.data?.message || '操作失败，请重试'
}

async function submitPassword() {
  if (loading.value) return
  error.value = ''

  if (!account.value || !password.value || !captchaCode.value) {
    error.value = '请填写账号、密码和验证码'
    return
  }
  if (!captcha.value) {
    error.value = '验证码加载失败，点图片重试'
    return
  }

  loading.value = true
  try {
    await login({
      account: account.value.trim(),
      password: password.value,
      captcha_key: captcha.value.captcha_id,
      captcha_code: captchaCode.value.trim()
    })
    await navigateTo(destination())
  } catch (err) {
    error.value = messageOf(err)
    // 后端校验失败即删 key，必须换一张
    await loadCaptcha()
  } finally {
    loading.value = false
  }
}

/** 发送邮箱验证码，成功后在 60 秒内禁用按钮。 */
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
      body: { email: email.value.trim(), purpose: 'login' }
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

async function submitEmail() {
  if (loading.value) return
  error.value = ''

  if (!email.value.trim() || !emailCode.value.trim()) {
    error.value = '请填写邮箱和验证码'
    return
  }

  loading.value = true
  try {
    await loginByEmail({
      email: email.value.trim(),
      purpose: 'login',
      captcha: emailCode.value.trim()
    })
    await navigateTo(destination())
  } catch (err) {
    error.value = messageOf(err)
  } finally {
    loading.value = false
  }
}

/** 切换 Tab 时清掉上一次的报错，避免串味。 */
watch(mode, () => {
  error.value = ''
})
</script>

<template>
  <div>
    <h1 class="font-serif text-[1.75rem] font-semibold text-stone-900 dark:text-stone-100">
      登录
    </h1>
    <p class="mt-2 text-sm text-stone-400 dark:text-stone-500">
      欢迎回来。
    </p>

    <!-- Tab：不用组件库的胶囊样式，用下划线，更安静 -->
    <div class="mt-10 flex gap-6 border-b border-stone-200 dark:border-stone-800">
      <button
        v-for="tab in [
          { key: 'password', label: '账号密码' },
          { key: 'email', label: '邮箱验证码' }
        ]"
        :key="tab.key"
        type="button"
        class="-mb-px border-b pb-3 text-sm transition-colors"
        :class="mode === tab.key
          ? 'border-stone-900 text-stone-900 dark:border-stone-100 dark:text-stone-100'
          : 'border-transparent text-stone-400 hover:text-stone-600 dark:text-stone-500 dark:hover:text-stone-300'"
        @click="mode = tab.key as 'password' | 'email'"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- 密码登录 -->
    <form
      v-if="mode === 'password'"
      class="mt-8 space-y-5"
      @submit.prevent="submitPassword"
    >
      <input
        v-model="account"
        type="text"
        inputmode="numeric"
        autocomplete="username"
        placeholder="账号"
        class="w-full border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900
               dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
      >

      <input
        v-model="password"
        type="password"
        autocomplete="current-password"
        placeholder="密码"
        class="w-full border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900
               dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
      >

      <div class="flex items-end gap-3">
        <input
          v-model="captchaCode"
          type="text"
          inputmode="numeric"
          maxlength="6"
          autocomplete="off"
          placeholder="验证码"
          class="min-w-0 flex-1 border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900
                 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900
                 dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
        >
        <button
          type="button"
          class="shrink-0 overflow-hidden rounded border border-stone-200 transition-opacity hover:opacity-70
                 dark:border-stone-800"
          title="点击换一张"
          @click="loadCaptcha"
        >
          <img
            v-if="captcha"
            :src="captcha.base_64"
            alt="验证码"
            class="block h-10 w-28 object-cover"
          >
          <span
            v-else
            class="flex h-10 w-28 items-center justify-center text-xs text-stone-400"
          >点击加载</span>
        </button>
      </div>

      <p
        v-if="error"
        class="pt-1 text-xs text-rose-600 dark:text-rose-400"
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
        {{ loading ? '登录中…' : '登录' }}
      </button>
    </form>

    <!-- 邮箱验证码登录 -->
    <form
      v-else
      class="mt-8 space-y-5"
      @submit.prevent="submitEmail"
    >
      <input
        v-model="email"
        type="email"
        autocomplete="email"
        placeholder="邮箱"
        class="w-full border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900
               outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900
               dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
      >

      <div class="flex items-end gap-3">
        <input
          v-model="emailCode"
          type="text"
          inputmode="numeric"
          maxlength="6"
          autocomplete="one-time-code"
          placeholder="6 位验证码"
          class="min-w-0 flex-1 border-b border-stone-200 bg-transparent py-3 text-[0.95rem] text-stone-900
                 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900
                 dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100"
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

      <p
        v-if="error"
        class="pt-1 text-xs text-rose-600 dark:text-rose-400"
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
        {{ loading ? '登录中…' : '登录' }}
      </button>
    </form>

    <div class="mt-10 flex items-center justify-between text-xs">
      <NuxtLink
        to="/register"
        class="text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
      >
        还没有账号
      </NuxtLink>
      <NuxtLink
        to="/forgot-password"
        class="text-stone-400 transition-colors hover:text-stone-900 dark:text-stone-500 dark:hover:text-stone-100"
      >
        忘记密码
      </NuxtLink>
    </div>
  </div>
</template>
