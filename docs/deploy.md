# 部署

三种场景，按需要选：

| 场景 | 用哪个 compose | 说明 |
|---|---|---|
| 本地开发 | `docker-compose.yml` | 全套依赖，一条命令起来 |
| 单机生产（空机器） | `docker-compose.yml` | 同上，但要配真实域名与密钥 |
| 复用已有基础设施 | `docker-compose.prod.yml` | 只跑应用，连宿主机上已有的 MySQL / Redis / MinIO |

---

## 1. 本地全栈

```bash
cp configs/config.yaml.example configs/config.yaml   # 可选，compose 会用环境变量覆盖
docker compose up -d --build

# 等 MySQL 初始化完（首次约 30 秒）
docker compose ps

curl http://127.0.0.1:8000/api/v1/health
```

端口分配：

| 服务 | 宿主机端口 | 说明 |
|---|---|---|
| app | 8000 | 后端 |
| mysql | 3307 | 映射到 3307，避开本机已有的 3306 |
| redis | 6380 | 同上 |
| minio | 9000 / 9001 | 9001 是控制台 |

首次启动会自动建表（容器 CMD 里先跑 `alembic upgrade head`），
并按配置创建默认管理员。

---

## 2. 生产：复用已有服务

### 2.1 前置条件

宿主机上已有 MySQL 8 / Redis / MinIO，且：

- MySQL 里建好库 `blog_v2`（utf8mb4）
- MinIO 里建好桶 `blog-v2`
- 有一个只对 `blog_v2` 库有权限的账号（**别用 root**）

```sql
CREATE DATABASE IF NOT EXISTS `blog_v2`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'blog'@'%' IDENTIFIED BY '换成强密码';
GRANT ALL PRIVILEGES ON `blog_v2`.* TO 'blog'@'%';
FLUSH PRIVILEGES;
```

### 2.2 准备 `.env`

```bash
SITE_URL=https://你的域名
MYSQL_HOST=172.17.0.1          # docker0 网桥，容器访问宿主机的地址
MYSQL_USER=blog
MYSQL_PASSWORD=换成强密码
MYSQL_DATABASE=blog_v2
REDIS_HOST=172.17.0.1
JWT_SECRET=$(openssl rand -hex 32)
FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
MINIO_ENDPOINT=172.17.0.1:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=blog-v2
MINIO_PUBLIC_URL=https://你的域名
ADMIN_PASSWORD=换成强密码
WORKERS=2
```

> `MINIO_ENDPOINT` 是**容器访问 MinIO 的地址**，`MINIO_PUBLIC_URL` 是**浏览器访问图片的地址**。
> 两个不一样：前者走内网，后者走公网。写成一样会导致图片 403 或打不开。

### 2.3 起服务

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f app
```

日志里要能看到：

```
依赖状态 | MySQL=OK | Redis=OK | MinIO=OK
已创建默认管理员 account=...
服务已就绪
```

### 2.4 Nginx 反代

如果 80/443 已经被别的容器占了，在现有 Nginx 配置里加一段：

```nginx
# 新后端
location /api/v1/ {
    proxy_pass http://172.17.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # 摘要生成要调大模型，耗时 3-10 秒；默认 60s 在慢模型上会 504
    proxy_read_timeout 120s;
}

# 邮件里的换绑链接会直接打开一个 HTML 页面
location = /api/v1/user/email {
    proxy_pass http://172.17.0.1:8000;
    proxy_set_header Host $host;
}
```

改完 `nginx -s reload`（或重启 frontend 容器）。

---

## 3. 升级

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

容器启动时会自动跑 `alembic upgrade head`，不用手工迁移。

**回滚**：镜像按 tag 保留，回退到上一个版本：

```bash
docker compose -f docker-compose.prod.yml down
docker tag blog-v2-backend:previous blog-v2-backend:latest
docker compose -f docker-compose.prod.yml up -d
```

---

## 4. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 容器反复重启 | MySQL 还没就绪 | `docker compose logs app` 看是不是连接被拒；`depends_on` 的 `start_period` 要给足 40s |
| `MySQL=FAIL` 但服务能起来 | 库连不上 | 检查 `MYSQL_HOST`：容器里写 `127.0.0.1` 是错的，那是容器自己 |
| 图片 403 / 打不开 | `MINIO_PUBLIC_URL` 配错 | 必须是浏览器能访问的纯源地址，不要带路径前缀 |
| 换绑邮箱点链接 404 | Nginx 没转 `/api/v1/user/email` | 见上面 Nginx 配置 |
| 摘要接口 504 | 反代超时太短 | `proxy_read_timeout` 调到 120s |
| `alembic upgrade` 报「表已存在」 | 库里有另一套 schema | 确认连的是 `blog_v2` 而不是旧库 |

### 看日志

```bash
docker compose -f docker-compose.prod.yml logs -f --tail=100 app
tail -f logs/app_$(date +%Y-%m-%d).log
```

应用日志同时写 stdout 和 `logs/` 目录（挂载到宿主机），容器重建不丢。
