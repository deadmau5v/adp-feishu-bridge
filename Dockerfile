# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────
# ADP-Feishu Bridge - production image
# Multi-stage build: uv for deps, slim runtime for size
# ─────────────────────────────────────────────────────────────

FROM python:3.12-slim-bookworm AS builder

# uv: fast Python package manager
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /build

# 利用 layer 缓存：先拷 requirements
COPY requirements.txt .
# 用 venv 装到独立目录，最后整体拷到 runtime 镜像
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache-dir -r requirements.txt


# ────────────────────── runtime ──────────────────────
FROM python:3.12-slim-bookworm AS runtime

# 不需要 uv 了，runtime 用 venv 即可
# 但保留 ca-certificates / tini / tzdata 之类基础工具
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        tzdata \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# 从 builder 拷过来——镜像里没有 pip/uv，更小更安全
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# 应用代码
COPY main.py config.py constants.py adp_client.py feishu_client.py handler.py ./
COPY .env.example .env.example

# 非 root 运行（uid/gid 1001 避开 SYS_UID_MAX 999 警告）
RUN groupadd --system --gid 1001 bridge && \
    useradd --system --uid 1001 --gid bridge --no-create-home --shell /sbin/nologin bridge && \
    chown -R bridge:bridge /app
USER bridge

# 端口：bridge 默认 8080（健康检查用；飞书长连接走出站，不依赖端口）
EXPOSE 8080

# tini 收僵尸进程，python -u 强制无缓冲
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "main.py"]
