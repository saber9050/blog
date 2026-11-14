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

// ---- 区块的「展示 / 编辑」开关 ----
//
// 个人中心的主职责是「看」，不是「改」：默认把资料当只读文本展示，
// 点各区块右上角的按钮才展开表单。这样页面不会一进来就是一堆输入框，
// 也顺手避免了「手滑改了昵称还不知道自己改了」。
const editingProfile = ref(false)
const editingEmail = ref(false)
const editingPwd = ref(false)

/** 进入资料编辑：用当前值填充输入框，并清掉上一轮的提示。 */
function startEditProfile() {
  nickName.value = profile.value?.user_name ?? ''
  introduction.value = profile.value?.introduction ?? ''
  profileMsg.value = ''
  profileErr.value = ''
  editingProfile.value = true
}

/** 取消资料编辑：输入框回滚到服务端值，避免下次打开还留着废弃的草稿。 */
function cancelEditProfile() {
  nickName.value = profile.value?.user_name ?? ''
  introduction.value = profile.value?.introduction ?? ''
  profileErr.value = ''
  editingProfile.value = false
}

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

/** 展开绑定 / 换绑表单。每次打开都是空白，不复用上次的输入。 */
function startEditEmail() {
  newEmail.value = ''
  emailPassword.value = ''
  emailCode.value = ''
  emailMsg.value = ''
  emailErr.value = ''
  editingEmail.value = true
}

function cancelEditEmail() {
  newEmail.value = ''
  emailPassword.value = ''
  emailCode.value = ''
  emailErr.value = ''
  editingEmail.value = false
}

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
    // 提交成功就收起表单：结果提示留在区块底部，不需要一直开着表单
    editingEmail.value = false
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

// 三个区块的按钮样式统一在这里，避免同一串 class 抄六遍
const btnGhost = 'rounded-md border border-stone-200 px-3 py-1.5 text-xs text-stone-600 transition-colors hover:border-stone-400 hover:text-stone-900 dark:border-stone-800 dark:text-stone-400 dark:hover:border-stone-600 dark:hover:text-stone-100'
const btnPrimary = 'rounded-md bg-stone-900 px-3.5 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50 dark:bg-stone-100 dark:text-stone-900'
const btnText = 'text-xs text-stone-400 transition-colors hover:text-stone-700 dark:text-stone-500 dark:hover:text-stone-300'

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
    // 保存成功收起表单，回到只读展示
    editingProfile.value = false
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

/** 展开改密表单。密码字段一律留空，不预填。 */
function startEditPwd() {
  oldPassword.value = ''
  newPassword.value = ''
  ackPassword.value = ''
  pwdMsg.value = ''
  pwdErr.value = ''
  editingPwd.value = true
}

function cancelEditPwd() {
  oldPassword.value = ''
  newPassword.value = ''
  ackPassword.value = ''
  pwdErr.value = ''
  editingPwd.value = false
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
    // 改完收起表单，提示留在区块里
    editingPwd.value = false
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

    <!-- 基本资料：默认只读展示，点「编辑」才出现输入框 -->
    <section class="mt-12">
      <div class="flex items-center justify-between">
        <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
          基本资料
        </h2>

        <button
          v-if="!editingProfile"
          type="button"
          :class="btnGhost"
          @click="startEditProfile"
        >
          编辑
        </button>
        <button
          v-else
          type="button"
          :class="btnText"
          @click="cancelEditProfile"
        >
          取消
        </button>
      </div>

      <!-- 展示态 -->
      <dl
        v-if="!editingProfile"
        class="mt-6 grid grid-cols-[4.5rem_1fr] gap-y-5 text-sm"
      >
        <dt class="pt-0.5 text-xs text-stone-400 dark:text-stone-500">
          昵称
        </dt>
        <dd class="text-stone-900 dark:text-stone-100">
          {{ profile.user_name }}
        </dd>

        <dt class="pt-0.5 text-xs text-stone-400 dark:text-stone-500">
          简介
        </dt>
        <dd class="leading-relaxed text-stone-700 dark:text-stone-300">
          {{ profile.introduction || '还没写简介' }}
        </dd>

        <dt class="pt-0.5 text-xs text-stone-400 dark:text-stone-500">
          账号
        </dt>
        <dd class="text-stone-500 dark:text-stone-400">
          {{ profile.account }}
          <span class="ml-2 text-xs text-stone-400 dark:text-stone-600">不可修改</span>
        </dd>
      </dl>

      <!-- 编辑态 -->
      <div
        v-else
        class="mt-6 space-y-6"
      >
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

        <p class="text-xs text-stone-400 dark:text-stone-600">
          账号 {{ profile.account }} 不可修改
        </p>

        <button
          type="button"
          :disabled="savingProfile"
          :class="btnPrimary"
          @click="saveProfile"
        >
          {{ savingProfile ? '保存中…' : '保存' }}
        </button>
      </div>

      <p
        v-if="profileMsg"
        class="mt-4 text-xs text-emerald-600 dark:text-emerald-500"
      >
        {{ profileMsg }}
      </p>
      <p
        v-if="profileErr"
        class="mt-4 text-xs text-rose-600 dark:text-rose-400"
      >
        {{ profileErr }}
      </p>
    </section>

    <!-- 邮箱：展示当前邮箱，点按钮才展开绑定 / 换绑表单 -->
    <section class="mt-12 border-t border-stone-200 pt-10 dark:border-stone-800">
      <div class="flex items-center justify-between">
        <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
          邮箱
        </h2>

        <button
          v-if="!editingEmail"
          type="button"
          :class="btnGhost"
          @click="startEditEmail"
        >
          {{ hasEmail ? '换绑' : '绑定邮箱' }}
        </button>
        <button
          v-else
          type="button"
          :class="btnText"
          @click="cancelEditEmail"
        >
          取消
        </button>
      </div>

      <!-- 展示态 -->
      <p
        v-if="!editingEmail"
        class="mt-5 text-sm"
      >
        <span :class="hasEmail ? 'text-stone-900 dark:text-stone-100' : 'text-stone-400 dark:text-stone-500'">
          {{ profile.email || '未绑定' }}
        </span>
        <span
          v-if="!hasEmail"
          class="ml-3 text-xs text-stone-400 dark:text-stone-600"
        >
          绑定后可用邮箱验证码登录、找回密码
        </span>
      </p>

      <!-- 编辑态 -->
      <div
        v-else
        class="mt-5 space-y-4"
      >
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

        <!-- 验证码 -->
        <input
          v-model="emailCode"
          type="text"
          inputmode="numeric"
          maxlength="6"
          autocomplete="one-time-code"
          placeholder="6 位验证码"
          :class="inputClass"
        >

        <p class="text-[11px] leading-relaxed text-stone-400 dark:text-stone-600">
          <template v-if="hasEmail">
            换绑分两步：验证码发到<strong class="font-normal text-stone-500 dark:text-stone-400">当前邮箱</strong>（证明是本人），
            校验通过后再给<strong class="font-normal text-stone-500 dark:text-stone-400">新邮箱</strong>发确认链接，点链接才生效。
          </template>
          <template v-else>
            验证码会发到你要绑定的邮箱，填进来即可完成绑定。
          </template>
        </p>

        <button
          type="button"
          :disabled="bindingEmail"
          :class="btnPrimary"
          @click="bindEmail"
        >
          {{ bindingEmail ? '提交中…' : hasEmail ? '申请换绑' : '绑定' }}
        </button>
      </div>

      <p
        v-if="emailMsg"
        class="mt-4 text-xs text-emerald-600 dark:text-emerald-500"
      >
        {{ emailMsg }}
      </p>
      <p
        v-if="emailErr"
        class="mt-4 text-xs text-rose-600 dark:text-rose-400"
      >
        {{ emailErr }}
      </p>
    </section>

    <!-- 密码：默认只显示状态，点「修改密码」才出现表单 -->
    <section class="mt-12 border-t border-stone-200 pt-10 dark:border-stone-800">
      <div class="flex items-center justify-between">
        <h2 class="font-serif text-base font-semibold text-stone-900 dark:text-stone-100">
          密码
        </h2>

        <button
          v-if="!editingPwd"
          type="button"
          :class="btnGhost"
          @click="startEditPwd"
        >
          修改密码
        </button>
        <button
          v-else
          type="button"
          :class="btnText"
          @click="cancelEditPwd"
        >
          取消
        </button>
      </div>

      <!-- 展示态 -->
      <p
        v-if="!editingPwd"
        class="mt-5 text-sm text-stone-500 dark:text-stone-400"
      >
        ********
        <span class="ml-3 text-xs text-stone-400 dark:text-stone-600">
          注册于 {{ formatDate(profile.create_at) }}
        </span>
      </p>

      <!-- 编辑态 -->
      <div
        v-else
        class="mt-5 space-y-5"
      >
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

        <button
          type="button"
          :disabled="changingPwd"
          :class="btnPrimary"
          @click="changePassword"
        >
          {{ changingPwd ? '提交中…' : '确认修改' }}
        </button>
      </div>

      <p
        v-if="pwdMsg"
        class="mt-4 text-xs text-emerald-600 dark:text-emerald-500"
      >
        {{ pwdMsg }}
      </p>
      <p
        v-if="pwdErr"
        class="mt-4 text-xs text-rose-600 dark:text-rose-400"
      >
        {{ pwdErr }}
      </p>
    </section>
  </div>
</template>
