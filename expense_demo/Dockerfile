FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    APP_ENV=prod

WORKDIR /app

# ===========================================================================
# 构建期网络（本次重构的核心修复）
# ---------------------------------------------------------------------------
# BuildKit 会把宿主机的 HTTP_PROXY / HTTPS_PROXY 等代理变量自动注入每一个 RUN。
# 本机代理常写成 http://127.0.0.1:<port>，但构建容器里 127.0.0.1 指向容器自身，
# 代理连接被拒 → pip 解析不到任何包版本 → 报
#   "Could not find a version that satisfies the requirement SQLAlchemy (from versions: none)"
# 这并非 SQLAlchemy 版本问题，而是代理污染。故在 pip 这一步用 env -u 显式移除
# 所有代理变量，让 pip 直连索引；并用国内镜像 + 重试参数提高构建稳定性。
#
# 若你的网络确实需要代理才能出网：不要改这里，改在运行层面用
#   docker build --build-arg HTTP_PROXY=http://真实代理:端口 ...
# 本文件默认假定构建容器可直连镜像源（Docker Desktop 的 NAT 网络通常可以）。
# ===========================================================================
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先单独 COPY 依赖清单：requirements 未变时，下面昂贵的 pip 层可直接走构建缓存。
COPY requirements.txt /app/requirements.txt

RUN env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
        -u ALL_PROXY -u all_proxy -u FTP_PROXY -u ftp_proxy \
        -u NO_PROXY -u no_proxy \
    pip install --no-cache-dir --retries 5 --timeout 30 \
        --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . /app

# 非 root 运行：创建无登录 shell 的应用用户，仅授予数据目录写权限。
# /app 内的代码只读即可，数据库写在挂载的 /app/data（已 chown）。
RUN useradd --system --create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app/data
USER appuser

# .env 说明：配置由 docker-compose 的 env_file 注入为环境变量（config.py 从 os.environ 读取），
# 且 .env 被 .dockerignore 排除，镜像内没有也不需要 .env 文件。APP_ENV=prod 是镜像内置安全默认。

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)" || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false"]
