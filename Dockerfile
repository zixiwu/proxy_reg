# Python 3.11 slim：项目要求 Python 3.10+，README 建议 3.11+
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/home/appuser

WORKDIR /app

# 浏览器运行库：Turnstile Solver 内置在镜像中，容器启动即可求解，无需宿主机额外安装
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgtk-3-0 libasound2 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
        libgbm1 libxkbcommon0 libpango-1.0-0 libcairo2 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libnspr4 libnss3 libxfixes3 libdbus-glib-1-2 libxt6 \
        fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单，源码变动时可复用这一层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements_camoufox.txt ./
RUN pip install --no-cache-dir -r requirements_camoufox.txt

# 预下载 camoufox 浏览器到 appuser 家目录，运行期不再联网下载
RUN useradd --create-home --uid 10001 appuser \
    && HOME=/home/appuser python -m camoufox fetch \
    && chown -R appuser:appuser /home/appuser

# 再复制项目源码
COPY . .

# 预建产物目录；setpriv 用于入口脚本降权
RUN mkdir -p /app/keys \
    && chown -R appuser:appuser /app \
    && (command -v setpriv >/dev/null 2>&1 || (apt-get update && apt-get install -y --no-install-recommends util-linux && rm -rf /var/lib/apt/lists/*))

# 入口脚本以 root 启动，修正 bind mount 的 keys/ 属主后降权到 appuser 运行
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 5080

# 探活：/api/health 为公开接口
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('WEB_PORT','5080'), timeout=3)"

# 默认启动 Web 管理台；批量注册可改为 python main.py
CMD ["python", "web_app.py"]
