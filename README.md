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

# 4. 起服务
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

启动后：

- 接口文档 `http://127.0.0.1:8000/docs`（`app.mode=debug` 时才开）
- 健康检查 `http://127.0.0.1:8000/api/v1/health`
- 默认管理员 `00000000000` / `admin123456`（首次启动自动创建，**登录后立刻改**）

### 启动命令怎么读

```
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
└──────── 解释器 ────────┘ └─ 模块 ─┘ └ 入口 ┘
```

`app.main:app` 是「模块路径 **:** 变量名」，uvicorn 实际在做 `from app.main import app`：

| 片段 | 指向 |
|---|---|
| `app` | `backend/app/` 这个 Python 包 |
| `main` | `app/main.py` |
| `:app` | 文件末尾的 `app = create_app()` |

常用参数：

| 参数 | 说明 |
|---|---|
| `--reload` | 改代码自动重启，只用于开发 |
| `--host 0.0.0.0` | 允许局域网访问（默认 `127.0.0.1` 只有本机） |
| `--workers 2` | 多进程，生产用；**与 `--reload` 互斥** |
| `--log-level warning` | 只看结果不打过程日志 |

> `config.yaml` 里的 `app.host` / `app.port` **不控制监听地址**，只用于打印 banner
> 和文档链接。真正监听哪里由命令行决定，两处不一致时以命令行为准。
>
> 顺带：`fastapi dev` 这条命令在本项目用不了 —— `pyproject.toml` 只装了 `fastapi`
> 核心包，没装 `fastapi[standard]`（`fastapi-cli` 在后者里）。且 `dev` 是子命令，
> 写成 `fastapi run dev` 是错的，`run` 后面跟的是入口点。

依赖的服务：MySQL 8（必需）、Redis（可选，关掉时降级为进程内缓存）、
MinIO（可选，图片上传需要）、SMTP（可选，不配则验证码只打日志）。

## 在 /docs 里自测

`app.mode=debug` 时接口文档在 `http://127.0.0.1:8000/docs`，63 个接口都能点 **Try it out**。

需要登录的接口按这个顺序走一遍：

1. `GET /auth/image_captcha` → 拿到 `captcha_id` 和 `base_64`
2. `base_64` 是一整串 `data:image/png;base64,...`，Swagger 只显示文本。
   **复制整串粘到浏览器地址栏**就能看到那张 240×80 的验证码图
3. `POST /auth/login`，填：

   ```json
   {
     "account": "00000000000",
     "password": "admin123456",
     "captcha_key": "上一步的 captcha_id",
     "captcha_code": "你看图读出来的 6 位数字"
   }
   ```

4. 复制响应里的 `access_token`，点页面右上角 **Authorize**，粘贴进去点 Authorize。
   之后所有带锁图标的接口都会自动带上 `Authorization`，不用逐个填

两个容易踩的点：

- 登录响应**不含 `refresh_token`** —— 它藏在 access_token 的 `tid` claim 里，
  不对外暴露（防 XSS 拿到长期凭证）。`POST /auth/refresh` 要传 access_token 本体，
  过期的也行
- 验证码是一次性的，输错或过期都要重新取一张

## 测试与检查

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/ -q          # 172 条，真连 MySQL
.venv/Scripts/python.exe -m ruff check app tests alembic scripts
.venv/Scripts/python.exe scripts/check_api_contract.py  # 文档 vs 实际路由
```

测试**不是 mock 数据库的**：SQL 写错、索引漏建、软删除过滤错这类问题，
只有真连库才暴露得出来。

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
