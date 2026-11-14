# blog

个人博客系统。后端 Python / FastAPI + MySQL 8，前端待开发。

## 目录

```
blog/
├── backend/   后端（FastAPI + SQLAlchemy async + MySQL 8）
├── web/       前端（待开发）
└── docs/      需求、接口契约、模块设计与部署手册
```

后端与前端各自独立构建、独立部署：后端出 Docker 镜像，前端出静态产物。
`docker-compose*.yml` 放在根目录，负责编排整个项目。

## 快速启动（后端）

```bash
cd backend

# 1. 创建虚拟环境并装依赖
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"     # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS / Linux

# 2. 准备配置（真实配置文件不入库）
cp configs/config.yaml.example configs/config.yaml
#    然后填数据库密码、jwt.secret、security.fernet_key

# 3. 建表
.venv/Scripts/python.exe -m alembic upgrade head

# 4. 起服务（三选一）
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python.exe app/main.py          # 直接跑入口，PyCharm 右键 Run 也行
.venv/Scripts/python.exe -m fastapi dev app/main.py
```

> 从哪个目录启动都行：配置文件和日志目录都按 `backend/` 解析，不看当前工作目录。
> 配置没找到时会往 stderr 打一行醒目提示，不会静默用默认值。

启动后：

- 接口文档 `http://127.0.0.1:8000/docs`（`app.mode=debug` 时才开）
- 健康检查 `http://127.0.0.1:8000/api/v1/health`
- 默认管理员 `00000000000` / `admin123456`（首次启动自动创建，**登录后立刻改**）

依赖的服务：MySQL 8（必需）、Redis（可选，关掉时降级为进程内缓存）、
MinIO（可选，图片上传需要）、SMTP（可选，不配则验证码只打日志）。

调试或写自动化脚本需要 token 时，**不要调登录接口** —— 本项目是单设备登录，
`refresh:{user_id}` 只有一个 key，任何一次新登录都会覆盖它，把正在用的浏览器顶下线。
用这个脚本复用当前会话签 token，不发登录请求：

```bash
.venv/Scripts/python.exe scripts/mint_token.py              # 正常 token
.venv/Scripts/python.exe scripts/mint_token.py --expired    # 已过期，用来验证刷新链路
```

## 测试与检查

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/ -q          # 172 条，真连 MySQL
.venv/Scripts/python.exe -m ruff check app tests alembic scripts
.venv/Scripts/python.exe scripts/check_api_contract.py  # 文档 vs 实际路由
```

测试**不是 mock 数据库的**：SQL 写错、索引漏建、软删除过滤错这类问题，
只有真连库才暴露得出来。

## 快速启动（前端）

```bash
cd web
pnpm install
pnpm dev          # http://localhost:3000
```

开发服务器的 `/api` 会转发到 `127.0.0.1:8000`，所以先起后端。

需要 Node 20+（本机默认是 14，要先 `nvm use 22`）。

技术栈与页面清单见 [web/README.md](web/README.md)。

## 容器化

```bash
docker compose up -d --build                        # 本地全栈（自带 MySQL/Redis/MinIO）
docker compose -f docker-compose.prod.yml up -d     # 生产：只跑 app，复用已有中间件
```

后端镜像的构建上下文是 `./backend`，`.dockerignore` 也在那一层。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 索引、设计决策清单、开发规范、接口进度 |
| [docs/rewrite-plan.md](docs/rewrite-plan.md) | 重写总方案：取舍、结构、数据层、部署 |
| [docs/deploy.md](docs/deploy.md) | 部署手册与排障 |
| `docs/00-foundation` … `07-llm` | 各模块 `api.md`（契约）+ `design.md`（实现） |

接口契约以 `docs/*/api.md` 为准，代码必须与它一致 ——
`scripts/check_api_contract.py` 会把两者的路径与方法逐条比对，不一致就报错。
