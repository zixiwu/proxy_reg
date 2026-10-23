#!/bin/sh
# 容器以 root 启动时：修正 bind mount 的属主，再降权到 appuser 执行应用；
# 若运行时通过 --user 指定了用户，则直接执行。
set -e

APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/keys
    chown -R "$APP_UID:$APP_GID" /app/keys 2>/dev/null || true
    if [ -f /app/.env ]; then
        chown "$APP_UID:$APP_GID" /app/.env 2>/dev/null || true
    fi
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups "$@"
fi

exec "$@"
