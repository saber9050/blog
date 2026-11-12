// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  modules: [
    '@nuxt/eslint',
    '@nuxt/ui'
  ],

  devtools: {
    // 默认关闭：它会在页面底部压一条固定浮条，正好盖住页脚，
    // 而且非前端开发时用不到。需要时改 true 或按 Shift+Alt+D
    enabled: false
  },

  app: {
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      titleTemplate: '%s · 之间',
      title: '之间',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: '一个写代码与写生活的地方。' }
      ],
      link: [
        // 字体走系统栈，不引 Google Fonts：
        // 1) 国内直连 fonts.googleapis.com 基本不通，会阻塞首屏渲染
        // 2) 中文衬线光「思源宋体」一个 Regular 就 8 MB，为标题多拉 8 MB 不划算
        // 系统字体（苹方 / 微软雅黑 / 宋体）已经够用，真要自托管字体时再单独加
        { rel: 'icon', href: '/favicon.ico' }
      ]
    }
  },

  css: ['~/assets/css/main.css'],

  /**
   * 关闭 `@nuxt/fonts`（Nuxt UI 带进来的）。
   *
   * 它会扫描 CSS 里所有 font-family，再去 Google Fonts / npm 下载对应字体。
   * 我们用的是系统字体栈，它会把 `-apple-system` 当成 npm 包去装，必然失败；
   * Google 那几个 provider 在国内也连不通，每次启动刷一屏 502 并拖慢冷启动。
   * 本来就只用系统字体，关掉最干净。
   */
  fonts: false,

  /**
   * 接口地址。
   *
   * - 浏览器端用 `public.apiBase`（相对路径），走同源请求：
   *   开发时由下面的 devProxy 转发，生产由 Nginx 反代，前端不写死后端地址。
   * - 服务端渲染时没有「同源」概念，直接打 `apiBaseServer`。
   *
   * 部署到别的机器只需改环境变量：NUXT_API_BASE_SERVER=http://backend:8000/api/v1
   */
  runtimeConfig: {
    apiBaseServer: 'http://127.0.0.1:8000/api/v1',
    public: {
      apiBase: '/api/v1'
    }
  },

  compatibilityDate: '2026-06-30',

  /**
   * 开发期代理，只在 `nuxt dev` 生效。生产由 Nginx 反代 /api。
   */
  nitro: {
    devProxy: {
      '/api': {
        target: 'http://127.0.0.1:8000/api',
        changeOrigin: true
      }
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  }
})
