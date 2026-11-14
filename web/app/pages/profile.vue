<script setup lang="ts">
import type { UserProfile } from '~/types/api'

/**
 * 个人设置。
 *
 * 四块内容各自独立提交，不做「一个大表单」：
 * 头像上传、资料保存、换绑邮箱、改密码的接口与错误处理都不一样，
 * 混在一起会让「保存成功了但头像没上传」这种半成功状态很难表达。
 *
 * `ssr` 关闭在 `nuxt.config.ts` 的 routeRules 里配（页面级 definePageMeta 不生效）：
 * 页面数据全靠登录态，而 token 只在 localStorage 里，服务端渲染时请求必然 401。
 */
definePageMeta({ middleware: 'auth' })

const api = useApi()
const { user } = useAuth()

const { data: profile, refresh } = await useAsyncData('my-profile', () =>
  api.request<UserProfile>('/user/info')
)

// ---- 资料 ----
const nickName = ref('')
const introduction = ref('')
const savingProfile = ref(false)
const profileMsg = ref('')
const profileErr = ref('')

watch(
  profile,
  (value) => {
    if (!value) return
    nickName.value = value.user_name
    introduction.value = value.introduction
  },
  { immediate: true }
)

// ---- 头像 ----
const avatarUrl = ref('')
const uploading = ref(false)
const avatarErr = ref('')

watch(
  profile,
  (value) => {
    if (value) avatarUrl.value = value.avatar_url
  },
  { immediate: true }
)

// ---- 邮箱 ----
//
// 两条流程差别很大，前端必须分开走：
//   · 没绑过邮箱 → /user/add_email：验证码发到**新邮箱**，校验通过直接生效
//   · 已绑过邮箱 → /user/email_ack：验证码发到**当前邮箱**（证明是本人），
//     校验通过只给**新邮箱**发一封确认链接，点链接才真正换绑
// 两个接口都必须带 6 位验证码，所以界面上要有「发送验证码」和验证码输入框。
const newEmail = ref('')
const emailPassword = ref('')
const emailCode = ref('')
const bindingEmail = ref(false)
const sendingCode = ref(false)
const emailCountdown = ref(0)
const emailMsg = ref('')
const emailErr = ref('')

const hasEmail = computed(() => Boolean(profile.value?.email))

let emailTimer: ReturnType<typeof setInterval> | null = null

onBeforeUnmount(() => {
  if (emailTimer) clearInterval(emailTimer)
})

/**
 * 发送验证码。
 *
 * 目标邮箱按场景不同：换绑发到当前邮箱，首次绑定发到新邮箱 ——
 * 这一点反直觉，界面上也有对应文案说明，否则用户会去新邮箱里傻等。
 */
async function sendEmailCode() {
  if (sendingCode.value || emailCountdown.value > 0) return
  emailMsg.value = ''
  emailErr.value = ''

  const target = hasEmail.value ? (profile.value?.email ?? '') : newEmail.value.trim()
  if (!target) {
    emailErr.value = '请先填写要绑定的邮箱'
    return
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) {
    emailErr.value = '邮箱格式不正确'
    return
  }

  sendingCode.value = true
  try {
    await api.request('/auth/captcha', {
      method: 'POST',
      body: {
        email: target,
        purpose: hasEmail.value ? 'reset_email' : 'add_email'
      }
    })
    emailMsg.value = hasEmail.value
      ? `验证码已发送到当前邮箱 ${target}，请查收`
      : `验证码已发送到 ${target}，请查收`

    // 与后端 60 秒限流对齐，避免连点白等
    emailCountdown.value = 60
    emailTimer = setInterval(() => {
      emailCountdown.value -= 1
      if (emailCountdown.value <= 0 && emailTimer) {
        clearInterval(emailTimer)
        emailTimer = null
      }
    }, 1000)
  } catch (err) {
    emailErr.value = messageOf(err)
  } finally {
    sendingCode.value = false
  }
}

/** 提交绑定 / 换绑申请。换绑只发确认邮件，点链接后才生效。 */
async function bindEmail() {
  if (bindingEmail.value) return
  emailMsg.value = ''
  emailErr.value = ''

  const email = newEmail.value.trim()
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    emailErr.value = '邮箱格式不正确'
    return
  }
  if (!/^\d{6}$/.test(emailCode.value.trim())) {
    emailErr.value = '请填写 6 位验证码'
    return
  }
  if (hasEmail.value && !emailPassword.value) {
    emailErr.value = '换绑需要输入当前密码'
    return
  }

  bindingEmail.value = true
  try {
    if (hasEmail.value) {
      await api.request('/user/email_ack', {
        method: 'POST',
        body: {
          password: emailPassword.value,
          captcha: emailCode.value.trim(),
          new_email: email
        }
      })
      emailMsg.value = '确认邮件已发送到新邮箱，点邮件里的链接完成换绑'
    } else {
      await api.request('/user/add_email', {
        method: 'POST',
        body: { new_email: email, captcha: emailCode.value.trim() }
      })
      emailMsg.value = '邮箱已绑定'
      await refresh()
    }

    newEmail.value = ''
    emailCode.value = ''
    emailPassword.value = ''
  } catch (err) {
    emailErr.value = messageOf(err)
  } finally {
    bindingEmail.value = false
  }
}

// ---- 密码 ----
const oldPassword = ref('')
const newPassword = ref('')
const ackPassword = ref('')
const changingPwd = ref(false)
const pwdMsg = ref('')
const pwdErr = ref('')

const inputClass = 'w-full border-b border-stone-200 bg-transparent py-2.5 text-sm text-stone-900 outline-none transition-colors placeholder:text-stone-300 focus:border-stone-900 dark:border-stone-800 dark:text-stone-100 dark:placeholder:text-stone-600 dark:focus:border-stone-100'

function messageOf(err: unknown): string {
  const e = err as { statusMessage?: string, data?: { message?: string } }
  return e.statusMessage || e.data?.message || '操作失败，请重试'
}

/** 保存昵称与简介。 */
async function saveProfile() {
  if (savingProfile.value) return
  profileMsg.value = ''
  profileErr.value = ''

  if (!nickName.value.trim()) {
    profileErr.value = '昵称不能为空'
    return
  }

  savingProfile.value = true
  try {
    await api.request('/user/profile', {
      method: 'POST',
      body: {
        nick_name: nickName.value.trim(),
        // 简介允许清空，所以传空串也有意义（后端把 "" 当作清空）
        introduction: introduction.value
      }
    })
    profileMsg.value = '已保存'
    // 昵称变了导航栏要跟着变
    if (user.value) user.value = { ...user.value, name: nickName.value.trim() }
    await refresh()
  } catch (err) {
    profileErr.value = messageOf(err)
  } finally {
    savingProfile.value = false
  }
}

/** 上传头像。用 FormData，不能带 Content-Type，交给浏览器自己生成 boundary。 */
async function uploadAvatar(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  avatarErr.value = ''
  if (file.size > 10 * 1024 * 1024) {
    avatarErr.value = '图片不能超过 10MB'
    return
  }

  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await api.request<{ avatar_url: string }>('/user/avatar', {
      method: 'POST',
      body: form
    })
    avatarUrl.value = res.avatar_url
  } catch (err) {
    avatarErr.value = messageOf(err)
  } finally {
    uploading.value = false
    // 允许重复选同一个文件
    input.value = ''
  }
}

/** 改密码。 */
async function changePassword() {
  if (changingPwd.value) return
  pwdMsg.value = ''
  pwdErr.value = ''

  if (!oldPassword.value || !newPassword.value) {
    pwdErr.value = '请填写当前密码和新密码'
    return
  }
  if (newPassword.value !== ackPassword.value) {
    pwdErr.value = '两次输入的新密码不一致'
    return
  }
  if (!/^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{11,20}$/.test(newPassword.value)) {
    pwdErr.value = '新密码需 11-20 位，且同时包含字母和数字'
    return
  }

  changingPwd.value = true
  try {
    await api.request('/user/password', {
      method: 'POST',
      body: {
        old_password: oldPassword.value,
        new_password: newPassword.value,
        ack: ackPassword.value
      }
    })
    pwdMsg.value = '密码已修改'
    oldPassword.value = ''
    newPassword.value = ''
    ackPassword.value = ''
  } catch (err) {
    pwdErr.value = messageOf(err)
  } finally {
    changingPwd.value = false
  }
}

useSeoMeta({ title: '个人设置' })
</script>

<template>
  <div v-if="profile">
    <h1 class="font-serif text-[1.75rem] font-semibold text-stone-900 dark:text-stone-100">
      个人设置
    </h1>

    <!-- 头像 -->
    <section class="mt-10 flex items-center gap-5">
      <img
        v-if="avatarUrl"
        :src="avatarUrl"
        alt="头像"
        class="size-16 rounded-full object-cover"
      >
      <div
        v-else
        class="flex size-16 items-center justify-center rounded-full bg-stone-100 text-lg
               text-stone-400 dark:bg-stone-800 dark:text-stone-500"
      >
        {{ profile.user_name.slice(0, 1) }}
      </div>

      <div>
        <label
          class="cursor-pointer rounded-md border border-stone-200 px-3 py-1.5 text-xs
                 text-stone-600 transition-colors hover:border-stone-400 hover:text-stone-900
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
        >
          {{ uploading ? '上传中…' : '更换头像' }}
          <input
            type="file"
            accept=".jpg,.jpeg,.png,.webp"
            class="hidden"
            :disabled="uploading"
            @change="uploadAvatar"
          >
        </label>
        <p class="mt-2 text-xs text-stone-400 dark:text-stone-600">
          jpg / png / webp，不超过 10MB
        </p>
        <p
          v-if="avatarErr"
          class="mt-1 text-xs text-rose-600 dark:text-rose-400"
        >
          {{ avatarErr }}
        </p>
      </div>
    </section>

    <!-- 基本资料 -->
    <section class="mt-12">
      <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
        基本资料
      </h2>

      <div class="mt-6 space-y-6">
        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">昵称</label>
          <input
            v-model="nickName"
            type="text"
            maxlength="15"
            :class="inputClass"
          >
        </div>

        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">简介</label>
          <textarea
            v-model="introduction"
            rows="3"
            placeholder="写点什么介绍自己"
            class="mt-1 w-full resize-none border-b border-stone-200 bg-transparent py-2.5 text-sm
                   text-stone-900 outline-none transition-colors placeholder:text-stone-300
                   focus:border-stone-900 dark:border-stone-800 dark:text-stone-100
                   dark:placeholder:text-stone-600 dark:focus:border-stone-100"
          />
        </div>

        <div>
          <label class="text-xs text-stone-400 dark:text-stone-500">账号</label>
          <p class="py-2.5 text-sm text-stone-400 dark:text-stone-600">
            {{ profile.account }}（不可修改）
          </p>
        </div>
      </div>

      <div class="mt-6 flex items-center gap-4">
        <button
          type="button"
          :disabled="savingProfile"
          class="rounded-md bg-stone-900 px-4 py-2 text-xs font-medium text-white
                 transition-opacity hover:opacity-90 disabled:opacity-50
                 dark:bg-stone-100 dark:text-stone-900"
          @click="saveProfile"
        >
          {{ savingProfile ? '保存中…' : '保存资料' }}
        </button>
        <span
          v-if="profileMsg"
          class="text-xs text-emerald-600 dark:text-emerald-500"
        >
          {{ profileMsg }}
        </span>
        <span
          v-if="profileErr"
          class="text-xs text-rose-600 dark:text-rose-400"
        >
          {{ profileErr }}
        </span>
      </div>
    </section>

    <!-- 邮箱 -->
    <section class="mt-14 border-t border-stone-200 pt-10 dark:border-stone-800">
      <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
        邮箱
      </h2>
      <p class="mt-2 text-xs text-stone-400 dark:text-stone-500">
        当前：
        <span class="text-stone-600 dark:text-stone-400">{{ profile.email || '未绑定' }}</span>
      </p>

      <div class="mt-5 space-y-4">
        <!-- 换绑才需要密码：证明操作者是本人 -->
        <input
          v-if="hasEmail"
          v-model="emailPassword"
          type="password"
          autocomplete="current-password"
          placeholder="当前密码"
          :class="inputClass"
        >

        <!-- 新邮箱 + 发送验证码 -->
        <div class="flex items-end gap-3">
          <input
            v-model="newEmail"
            type="email"
            autocomplete="email"
            :placeholder="hasEmail ? '新的邮箱地址' : '要绑定的邮箱地址'"
            :class="[inputClass, 'min-w-0 flex-1']"
          >
          <button
            type="button"
            :disabled="sendingCode || emailCountdown > 0"
            class="shrink-0 border-b border-stone-200 pb-2.5 text-xs text-stone-500
                   transition-colors hover:text-stone-900 disabled:text-stone-300
                   dark:border-stone-800 dark:text-stone-400 dark:hover:text-stone-100
                   dark:disabled:text-stone-700"
            @click="sendEmailCode"
          >
            {{ emailCountdown > 0 ? `${emailCountdown}s 后重发` : sendingCode ? '发送中…' : '发送验证码' }}
          </button>
        </div>

        <!-- 验证码 + 提交 -->
        <div class="flex items-end gap-3">
          <input
            v-model="emailCode"
            type="text"
            inputmode="numeric"
            maxlength="6"
            autocomplete="one-time-code"
            placeholder="6 位验证码"
            :class="[inputClass, 'min-w-0 flex-1']"
          >
          <button
            type="button"
            :disabled="bindingEmail"
            class="shrink-0 rounded-md border border-stone-200 px-3 py-2 text-xs text-stone-600
                   transition-colors hover:border-stone-400 hover:text-stone-900 disabled:opacity-50
                   dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
            @click="bindEmail"
          >
            {{ bindingEmail ? '提交中…' : hasEmail ? '申请换绑' : '绑定' }}
          </button>
        </div>
      </div>

      <p class="mt-3 text-[11px] leading-relaxed text-stone-400 dark:text-stone-600">
        <template v-if="hasEmail">
          换绑分两步：验证码发到<strong class="font-normal text-stone-500 dark:text-stone-400">当前邮箱</strong>（证明是本人），
          校验通过后再给<strong class="font-normal text-stone-500 dark:text-stone-400">新邮箱</strong>发确认链接，点链接才生效。
        </template>
        <template v-else>
          验证码会发到你要绑定的邮箱，填进来即可完成绑定。
        </template>
      </p>

      <p
        v-if="emailMsg"
        class="mt-3 text-xs text-emerald-600 dark:text-emerald-500"
      >
        {{ emailMsg }}
      </p>
      <p
        v-if="emailErr"
        class="mt-3 text-xs text-rose-600 dark:text-rose-400"
      >
        {{ emailErr }}
      </p>
    </section>

    <!-- 密码 -->
    <section class="mt-14 border-t border-stone-200 pt-10 dark:border-stone-800">
      <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
        修改密码
      </h2>

      <div class="mt-6 space-y-5">
        <input
          v-model="oldPassword"
          type="password"
          autocomplete="current-password"
          placeholder="当前密码"
          :class="inputClass"
        >
        <input
          v-model="newPassword"
          type="password"
          autocomplete="new-password"
          placeholder="新密码（11-20 位，字母+数字）"
          :class="inputClass"
        >
        <input
          v-model="ackPassword"
          type="password"
          autocomplete="new-password"
          placeholder="确认新密码"
          :class="inputClass"
        >
      </div>

      <div class="mt-6 flex items-center gap-4">
        <button
          type="button"
          :disabled="changingPwd"
          class="rounded-md border border-stone-200 px-4 py-2 text-xs text-stone-600
                 transition-colors hover:border-stone-400 hover:text-stone-900 disabled:opacity-50
                 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100"
          @click="changePassword"
        >
          {{ changingPwd ? '提交中…' : '修改密码' }}
        </button>
        <span
          v-if="pwdMsg"
          class="text-xs text-emerald-600 dark:text-emerald-500"
        >
          {{ pwdMsg }}
        </span>
        <span
          v-if="pwdErr"
          class="text-xs text-rose-600 dark:text-rose-400"
        >
          {{ pwdErr }}
        </span>
      </div>

      <p class="mt-6 text-xs text-stone-400 dark:text-stone-600">
        注册于 {{ formatDate(profile.create_at) }}
      </p>
    </section>
  </div>
</template>
