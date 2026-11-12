# ============================================================
# 多阶段构建
#
# 为什么必须多阶段：`asyncmy` 是 C 扩展，`pip install` 需要 gcc 编译。
# 单阶段镜像里会残留 gcc + libc6-dev（约 300 MB），而这些在运行时毫无用处。
# 多阶段让编译工具只存在于 builder 层，最终镜像只拷产物。
# ============================================================

# ---------------- 构建阶段 ----------------
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# asyncmy 的编译依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 分层的关键：依赖层必须与源码解耦。
#
# 直接 `COPY app` 再 `pip install .` 是错的 —— 源码一变，这一层缓存全废，
# 每次都重装一遍所有依赖（含 asyncmy 的 C 编译，2 分钟起）。
#
# 做法：先用一个只有 `__init__.py` 的空包骗过 setuptools，
# 把第三方依赖装进独立的一层；真实源码在下一层覆盖，
# 只做 `--no-deps` 重装项目本体（秒级）。
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --prefix=/install .

COPY app ./app

# --no-deps：依赖已经装好，这里只重装 blog-backend 自身
RUN pip install --prefix=/install --no-deps --force-reinstall .

# ---------------- 运行阶段 ----------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# tzdata 让 TZ 生效（slim 镜像默认没有时区库，DATETIME 会差 8 小时）
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

COPY --from=builder /install /usr/local

WORKDIR /app

# 迁移脚本与配置模板。真实配置由 compose 挂载覆盖，不打进镜像
COPY alembic.ini ./
COPY alembic ./alembic
COPY configs/config.yaml.example ./configs/config.yaml

# 非 root 运行：容器被攻破时，攻击者拿到的不是 root
#
# `logs` 必须在这里建出来并交给 app：loguru 启动时会 mkdir 并写文件，
# 目录不存在或属主不是 uid 1000 会直接抛 PermissionError 让进程起不来。
RUN useradd -m -u 1000 app \
    && mkdir -p /app/logs \
    && chown -R app:app /app
USER app

EXPOSE 8000

# 用 python 而不是 curl 做健康检查：slim 镜像里没有 curl，
# 为了一个 healthcheck 装个 curl 不值当
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys,urllib.request; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

# 启动前跑迁移：容器自愈能力强，不用人工记得「先 alembic upgrade」
# workers 用环境变量控制，默认 2（2 核机器够用，每个 worker 一份连接池）
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-2}"]
