# web

博客前端。Nuxt 4 + Nuxt UI 4 + Tailwind 4，服务端渲染。

旧版前端（Vue 3 SPA）留在原仓库 `blogProject/vue`，不复用 —— 后端重写时砍掉了
向量化与对话能力，旧前端有 6 个文件已经失去对应接口，且纯 SPA 的文章页搜索引擎抓不到正文。

## 技术栈

| 层 | 选择 | 说明 |
|---|---|---|
| 框架 | Nuxt 4 | 前台 SSR（SEO），后台可走 client-only |
| UI | Nuxt UI 4 | 基于 Tailwind v4 + Reka UI |
| 状态 | Pinia | 登录态、用户信息 |
| 请求 | `$fetch` | 经 `composables/useApi.ts` 统一解包与错误处理 |
| 样式 | Tailwind v4 + 自定义排版类 | 见 `app/assets/css/main.css` |
| 字体 | 系统字体栈 | 不引 Web Font，中文一个字重就 5-8 MB |

## 目录

```
web/
├── app/
│   ├── app.vue                  # 根组件：UApp + NuxtLayout
│   ├── app.config.ts            # Nuxt UI 主题（primary = stone）
│   ├── assets/css/main.css      # 设计基线 + 文章正文排版
│   ├── layouts/default.vue      # 前台布局：导航 + 页脚
│   ├── pages/
│   │   ├── index.vue            # 文章列表
│   │   ├── archive.vue          # 归档（按年月）
│   │   ├── about.vue            # 关于
│   │   └── articles/[article_id].vue
│   ├── composables/useApi.ts    # 请求封装（SSR/CSR 双地址、统一解包）
│   ├── utils/format.ts          # 时间格式化（含伪 UTC 的坑）
│   └── types/api.ts             # 接口类型，与 docs/*/api.md 对齐
└── nuxt.config.ts
```

## 开发

```bash
cd web
pnpm install
pnpm dev          # http://localhost:3000，/api 由 devProxy 转发到 8000
```

前置条件：Node 20+（本机 `nvm use 22`），后端已在 `127.0.0.1:8000` 启动。

其他命令：

```bash
pnpm lint         # ESLint（含 Tailwind 类名校验）
pnpm typecheck    # vue-tsc
pnpm build        # 生产构建
```

## 已完成

| 页面 | 状态 |
|---|---|
| 首页文章列表 | ✅ 分页、SSR、骨架屏、空态/错误态 |
| 文章详情 | ✅ Markdown 渲染、阅读时长、标签、SEO meta |
| 归档 | ✅ 按年月分组 |
| 关于 | ✅ 空字段自动隐藏 |

**未做**：登录/注册、后台管理（文章编辑、评论审核、分类标签、AI 模型配置）、点赞与评论交互。

## 与后端的约定

- 接口前缀 `/api/v1`，开发走 `nitro.devProxy`，生产走 Nginx 反代
- 统一响应 `{"code": 0, "message": "成功", "data": {...}}`，`data` 为空时字段不输出
- 鉴权 `Authorization: Bearer <access_token>`，401 用 refresh token 换新的
- **时间字段形如 `2026-11-09T21:39:04Z`，这个 `Z` 不是 UTC**，
  直接 `new Date()` 会多 8 小时。统一走 `utils/format.ts` 里的 `parseApiTime`
- 分页字段不统一：文章列表 `page_size`，后台用户列表 `pageSize`，照契约来

## 两个已知的坑

**1. 字体模块必须关掉**

`@nuxt/fonts`（Nuxt UI 带入）会扫描 CSS 里的 font-family 去下载字体。
系统字体栈里的 `-apple-system` 会被它当成 npm 包，必然失败；
Google provider 在国内也连不通。`nuxt.config.ts` 里已设 `fonts: false`。

**2. 注释里不要写 `*/` 序列**

`app/types/api.ts` 曾经把 `docs/*/api.md` 写进 JSDoc，其中的 `*/` 提前闭合了注释块，
后面的中文被当代码解析，ESLint 报出莫名其妙的「Module declaration names may only use quoted strings」。
