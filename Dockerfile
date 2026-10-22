# Python 3.11 slim：项目要求 Python 3.10+，README 建议 3.11+
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先复制依赖清单，源码变动时可复用这一层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再复制项目源码
COPY . .

# 非 root 用户运行，并预建产物目录
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/keys \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 5080

# 探活：/api/health 为公开接口
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('WEB_PORT','5080'), timeout=3)"

# 默认启动 Web 管理台；批量注册可改为 python main.py
CMD ["python", "web_app.py"]
