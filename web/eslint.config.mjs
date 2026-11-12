// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'
import betterTailwindcss from 'eslint-plugin-better-tailwindcss'
import { getDefaultAttributes } from 'eslint-plugin-better-tailwindcss/api/defaults'

export default withNuxt(
  betterTailwindcss.configs['correctness-error'],
  {
    settings: {
      'better-tailwindcss': {
        entryPoint: 'app/assets/css/main.css',
        attributes: [
          ...getDefaultAttributes(),
          ['^v-bind:ui$', [{ match: 'objectValues' }]]
        ]
      }
    }
  },
  {
    rules: {
      /**
       * main.css 里手写的布局类，不是 Tailwind utility，插件认不出来。
       * 这些类存在的理由写在 main.css 对应注释里（Tailwind 的响应式写法
       * 与 w-full/shrink-0 组合时会算错 flex 分配）。
       */
      'better-tailwindcss/no-unknown-classes': ['error', {
        ignore: [
          'editor-split',
          'editor-main',
          'editor-aside',
          'admin-shell',
          'admin-scroll',
          'admin-page-scroll'
        ]
      }]
    }
  }
)
