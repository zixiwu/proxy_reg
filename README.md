# proxy_reg

[![docker](https://github.com/zixiwu/proxy_reg/actions/workflows/docker.yml/badge.svg)](https://github.com/zixiwu/proxy_reg/actions/workflows/docker.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

ProxyScrape 账号批量注册与 Premium 试用代理自动获取工具。

把「注册 → 邮箱验证 → onboarding 问卷 → 激活试用 → 导出代理」整条链路封装为可脚本化、可容器化的流程，最终产出可直接导入代理客户端的端点列表。内置免费的临时邮箱客户端，无需任何第三方邮箱服务的密钥。

> 本项目仅供学习与研究，使用前请阅读[免责声明](#免责声明)。

## 特性

| 能力 | 说明 |
|------|------|
| 全链路自动化 | Turnstile 由本地 Solver 求解，注册、邮箱验证、问卷填写、试用激活、代理下载全程无需人工介入 |
| 零密钥收信 | 内置 tempmail.ing 客户端，自动申请临时邮箱、轮询收件箱、按正则提取验证码 |
| 双入口 | CLI 批量注册，以及带账号列表 / 剩余时长 / 流量展示的 Web 管理台 |
| 结果可复用 | 代理追加写入 `keys/proxies.txt`，可选推送到 Resin 兼容的订阅地址 |
| 容器化交付 | 单镜像部署，非 root 运行，内置健康检查；GitHub Actions 自动跑测试并推送镜像到 GHCR |
| 可编排 | 账号 JWT 过期可自动重登，代理列表可按账号增量下载 |

## 目录

- [特性](#特性)
- [工作原理](#工作原理)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置参考](#配置参考)
- [使用](#使用)
- [Docker](#docker)
- [临时邮箱模块](#临时邮箱模块)
- [输出文件](#输出文件)
- [项目结构](#项目结构)
- [开发](#开发)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

## 工作原理

```text
创建临时邮箱 ──► 注册（携带 Turnstile token）──► 触发验证码邮件
                                                      │
        下载 / 导出 ◄── 激活免费试用 ◄── 问卷 ◄── 邮箱验证 ◄── 轮询取码
```

| 步骤 | 说明 | 接口 |
|------|------|------|
| 1. 创建邮箱 | 向临时邮箱服务申请一次性地址 | `POST {TEMPMAIL_API_BASE}/generate` |
| 2. 注册 | 提交邮箱、密码与 Turnstile token | `POST /v2/v4/account/auth/register` |
| 3. 触发验证 | 主动请求发送验证码邮件 | `POST .../account/reset-verification-code` |
| 4. 收信取码 | 轮询收件箱并用正则提取验证码 | `GET {TEMPMAIL_API_BASE}/emails/{address}` |
| 5. 邮箱验证 | 提交验证码 | `POST .../account/verify-email` |
| 6. 问卷 | 完成 onboarding 表单（纯接口调用） | `POST /v2/typeform` |
| 7. 激活试用 | 确认问卷状态后领取试用 | `POST .../premium/claim-trial` |
| 8. 下载代理 | 拉取该账号的试用端点列表 | `GET .../premium/proxy-list/{accountId}` |
| 9. 推送订阅 | 全部账号成功后上传 | `PATCH {RESIN_SUBSCRIPTION_URL}` |

## 环境要求

- **只用 Docker**：宿主机只需 Docker + Compose。镜像已内置 Python 运行时、Turnstile Solver 与浏览器，直接看 [Docker](#docker) 一节，一条命令即可运行。
- **本机直接运行**：需要 Python 3.10+（推荐 3.11）与可用的 **Turnstile Solver**（仓库自带 `api_solver.py`，依赖浏览器内核）。
- 可访问 `https://api.tempmail.ing`

## 快速开始

### 1. 安装

```bash
git clone https://github.com/zixiwu/proxy_reg.git
cd proxy_reg

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python -m camoufox fetch         # Solver 依赖的浏览器内核
```

### 2. 配置

```bash
cp .env.example .env
```

`.env.example` 中只有占位值，不含任何真实凭据。最小可用配置：

```env
WEB_PASSWORD=changeme            # Web 管理台登录密码
TURNSTILE_SOLVER_URL=            # 留空默认 http://127.0.0.1:5072
REGISTER_PASSWORD=               # 留空表示每个账号随机生成
```

### 3. 启动 Turnstile Solver

> Docker 部署无需本步骤：镜像内置了 solver 与浏览器，见 [Docker](#docker)。

另开一个终端并保持运行：

```bash
python api_solver.py --browser_type camoufox --thread 1 --debug
```

默认监听 `0.0.0.0:5072`。Solver 不可用时注册环节会因拿不到 token 而失败。

### 4. 运行

```bash
python web_app.py     # Web 管理台：http://127.0.0.1:5080/
python main.py        # 命令行批量注册
```

## 配置参考

全部配置均可通过环境变量注入，也可在 Web 管理台的「配置」页修改并写回 `.env`。

### 临时邮箱（tempmail.ing）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TEMPMAIL_API_BASE` | `https://api.tempmail.ing/api` | API 根地址 |
| `TEMPMAIL_SITE_ORIGIN` | `https://tempmail.ing` | 请求头 origin / referer |
| `TEMPMAIL_DURATION` | `10` | `/generate` 的 duration 参数 |
| `MAIL_CODE_REGEX` | 空 | 验证码提取正则，留空使用内置规则 |
| `MAIL_SENDER_KEYWORDS` | 空 | 按发件人 / 主题过滤，逗号分隔，空表示不筛选 |
| `MAIL_POLL_INTERVAL` | `4` | 收件箱轮询间隔（秒） |
| `MAIL_POLL_TIMEOUT` | `150` | 收信总超时（秒） |
| `MAIL_REQUEST_TIMEOUT` | `15` | 单次 HTTP 请求超时（秒） |
| `MAIL_GENERATE_INTERVAL` | `15` | 两次创建邮箱的最小间隔（秒） |
| `MAIL_GENERATE_RETRIES` | `3` | 创建邮箱失败重试次数 |
| `MAIL_GENERATE_BACKOFF` | `10` | 重试退避基数（秒） |
| `MAIL_RATE_LIMIT_WAIT` | `5` | 命中限流（429）后的额外等待（秒） |
| `MAIL_DOMAIN_BLACKLIST` | `animatimg.com,tempmail.ing` | 跳过这些域名返回的邮件 |
| `MAIL_BLACKLIST_RETRIES` | `5` | 命中黑名单时重新申请邮箱的次数 |

### 注册

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REGISTER_PASSWORD` | 空（随机） | 固定密码；需满足长度 ≥ 8 且包含大写字母、数字、特殊字符 |
| `REGISTER_INTERVAL` | `5` | 两次注册之间的最小间隔（秒），0 表示不限制 |
| `REGISTER_COUNT` | 空 | 非交互式指定注册数量，空则由标准输入提示 |
| `PROXY_DOWNLOAD_PROTOCOL` | `http` | 下载代理时使用的协议模板 |
| `PROXY` | 空 | 供 HTTP 客户端使用的代理地址（可选） |
| `MAX_CAPTCHA_FAIL_ROUNDS` | `3` | Turnstile 连续失败多少轮后放弃当前账号 |

### Turnstile

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TURNSTILE_SOLVER_URL` | `http://127.0.0.1:5072` | Solver 服务地址，支持分机部署 |

调用方式：`GET {url}/turnstile?url=...&sitekey=...` 取得 `taskId`，再 `GET {url}/result?id=...` 获取 token。

### 远程订阅（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RESIN_SUBSCRIPTION_URL` | 空 | Resin 兼容订阅地址，空则跳过上传 |
| `RESIN_API_TOKEN` | 空 | Bearer 令牌 |
| `RESIN_ENABLED` | `true` | 总开关 |
| `RESIN_NAME` | `ProxyScrape` | 订阅显示名称 |
| `RESIN_UPDATE_INTERVAL` | `12h` | 订阅刷新间隔 |
| `RESIN_EPHEMERAL_NODE_EVICT_DELAY` | `72h0m0s` | 临时节点淘汰延迟 |
| `RESIN_EPHEMERAL` | `false` | 是否以临时节点方式提交 |
| `RESIN_INCREMENTAL_ALIVE_NODES` | `false` | 是否增量提交存活节点 |

未配置 `RESIN_SUBSCRIPTION_URL` 或 `RESIN_API_TOKEN` 时自动跳过上传，本地文件照常输出。

### Web 管理台配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WEB_HOST` | `127.0.0.1` | 监听地址；容器内需设为 `0.0.0.0` |
| `WEB_PORT` | `5080` | 监听端口 |
| `WEB_PASSWORD` | `admin` | 登录密码，部署时务必修改 |

### 验证码识别规则

`MAIL_CODE_REGEX` 留空时按以下顺序匹配：

1. `(?:email\s+)?verification\s+code\s*[:：]?\s*([0-9a-fA-F]{8,16})\b`：匹配「verification code: 94168d64e3」形式的句子；
2. `(?<![0-9a-fA-F])([0-9a-fA-F]{8,16})(?![0-9a-fA-F])`：兜底匹配正文中孤立的 8–16 位十六进制串。

ProxyScrape 的验证码即 8–16 位十六进制。适配其他服务时可自定义，例如六位数字：

```env
MAIL_CODE_REGEX=(?<!\d)(\d{6})(?!\d)
```

其他行为约定：

- 收信前会先调用 `reset-verification-code` 主动触发发信；120 秒未收到则自动重发一次。
- 邮箱请求始终直连，不使用 `PROXY`，避免出口 IP 被邮箱服务判定为风险来源。
- 已消费的邮件 ID 会被忽略，防止验证码被重复使用。

## 使用

### CLI 批量注册

```bash
python main.py
REGISTER_COUNT=5 python main.py   # 非交互式
```

典型输出：

```text
[*] 临时邮箱 API: https://api.tempmail.ing/api
[*] 开始 ProxyScrape 注册: xxx@domain
[*] 求解 Turnstile ...
[+] 注册 API 成功
[*] 开始邮箱验证流程...
[*] xxx@domain 收到验证邮件，验证码 94168d64e3
[+] 邮箱验证成功
[+] 问卷完成
[+] Premium 免费试用已激活
[✓] 代理下载成功: ... | 100 条
```

### Web 管理台

```bash
python web_app.py
```

访问 `http://127.0.0.1:5080/`，未登录会跳转至 `/login`。

| 路由 | 说明 |
|------|------|
| `/` | 账号列表、批量注册、运行日志、下载与删除 |
| `/config` | 配置读写，保存后热更新运行参数 |
| `POST /api/auth/login` | 登录，载荷 `{"password": "..."}` |
| `POST /api/auth/logout` | 退出登录 |
| `GET /api/accounts` | 账号列表，`?live=1` 拉取实时详情 |
| `POST /api/accounts/refresh` | 刷新单个账号；JWT 过期时自动重登并回写 token |
| `GET /api/accounts/download-proxies?email=` | 下载指定账号的代理文本 |
| `GET /api/proxies/download-all` | 下载全部代理 |
| `POST /api/proxies/upload-resin` | 上传到远程订阅，载荷 `{"live": true}` |
| `POST /api/accounts/delete` | 删除单个账号 |
| `POST /api/accounts/delete-all` | 清空账号 |
| `POST /api/register` | 启动注册，载荷 `{"count": N}` |
| `GET /api/register/status` | 注册任务状态 |
| `POST /api/register/stop` | 停止当前注册任务 |
| `GET /api/register/logs?since=N` | 增量拉取注册日志 |
| `GET /api/health` | 健康检查（公开） |
| `GET` / `POST /api/config` | 读取 / 写入配置 |

账号 JWT 有效期约 24 小时，过期后刷新或下载会触发自动重登，结果缓存在 `keys/account_details_cache.json`。

### 已有账号单独下载代理

```bash
python download_proxies.py                          # 读取账号文件最后一行
python download_proxies.py --all                    # 全部账号
python download_proxies.py --token <JWT> --account-id <UUID>
python download_proxies.py --protocol http
python download_proxies.py --all --from-file keys/proxyscrape_accounts.txt
```

## Docker

镜像内置 Turnstile Solver 与 camoufox 浏览器：宿主机只需要 Docker，不需要安装 Python、浏览器或 solver。

```bash
cp .env.example .env        # 首次部署必须创建，compose 会读取
docker compose up -d --build
```

启动后：

| 服务 | 作用 | 端口 |
|------|------|------|
| `proxyscrape` | Web 管理台 + 批量注册 | `${WEB_PORT:-5080}` |
| `solver` | Turnstile 求解（内置浏览器） | 仅容器内网 `5072` |

管理台默认地址 `http://127.0.0.1:5080`，密码见 `.env` 的 `WEB_PASSWORD`。

镜像约 5.3 GB，其中 camoufox 自带的 Firefox 约 2.4 GB。浏览器在构建阶段下载并固化进镜像，运行期不再联网拉取；首次构建需下载约 500 MB 资源，耗时数分钟。宿主机建议预留 10 GB 磁盘。

### 常用操作

```bash
docker compose ps                                              # 两个服务状态（solver 带健康检查）
docker compose logs -f solver                                  # 求解日志
docker compose exec --user appuser proxyscrape python main.py  # 手工跑一次 CLI 注册
docker compose run --rm --user appuser proxyscrape python main.py
docker compose down                                            # 停止
```

容器主进程以 `appuser(10001)` 运行；`docker compose exec/run` 默认以 root 进入容器，执行会写 `keys/` 的命令时请加 `--user appuser`，避免宿主机上出现 root 属主的产物文件。

不使用 compose 时，需要自行提供 solver（可与应用共用同一镜像的两个容器）：

```bash
docker build -t proxy_reg .
docker network create proxyreg

docker run -d --name solver --network proxyreg --shm-size=1g \
  proxy_reg python api_solver.py --browser_type camoufox --thread 1 --host 0.0.0.0 --port 5072

docker run -d --name proxy_reg --network proxyreg \
  -p 5080:5080 --env-file .env \
  -e WEB_HOST=0.0.0.0 -e TURNSTILE_SOLVER_URL=http://solver:5072 \
  -v "$PWD/keys:/app/keys" -v "$PWD/.env:/app/.env" \
  --add-host host.docker.internal:host-gateway \
  --restart unless-stopped proxy_reg
```

### 使用 CI 构建的镜像

GitHub Actions 会把镜像推送到 `ghcr.io/zixiwu/proxy_reg`，公开可拉取：

```bash
docker pull ghcr.io/zixiwu/proxy_reg:latest

IMAGE=ghcr.io/zixiwu/proxy_reg:latest docker compose pull
IMAGE=ghcr.io/zixiwu/proxy_reg:latest docker compose up -d
```

可用标签：`latest` 与分支名（如 `main`）指向默认分支最新构建；打 `v*` 标签会额外产出 `1.0.0`、`1.0`、`v1.0.0`。

### 更新与回滚

```bash
IMAGE=ghcr.io/zixiwu/proxy_reg:latest docker compose pull
IMAGE=ghcr.io/zixiwu/proxy_reg:latest docker compose up -d

IMAGE=ghcr.io/zixiwu/proxy_reg:1.0.0 docker compose up -d   # 回滚到指定版本
```

### 部署说明

- 镜像基于 `python:3.11-slim`，内置 camoufox 浏览器与 Turnstile Solver，`docker compose up -d --build` 后两个服务自动就绪。
- 应用与 solver 均以非 root 的 `appuser(10001)` 运行；solver 需要 `/dev/shm`，compose 中已设置 `shm_size: 1gb`，单容器运行时请加 `--shm-size=1g`。
- `keys/` 与 `.env` 通过 bind mount 持久化；Web 配置页的修改会写回宿主机 `.env`。
- 容器入口脚本以 root 启动，先把 `/app/keys` 与 `/app/.env` 修正为 `appuser(10001)` 所有，再降权执行应用，宿主机无需预先 chown。若在 compose 中显式指定 `user:`，则跳过该修正，需保证宿主机目录对该用户可写。
- 镜像目前仅构建 `linux/amd64`。在 ARM 设备上可使用 `--platform linux/amd64`（经 QEMU 模拟，性能有损耗），或打开 workflow 中 `platforms` 注释项重建多架构镜像。
- `PROXY` 指向宿主机服务时，同样需要使用 `host.docker.internal`。

### 部署排错（实测记录）

下面几条来自真实的 Docker 部署验证，按「现象 → 原因 → 处理」列出。

| 现象 | 原因 | 处理 |
|------|------|------|
| 日志反复出现 `Failed to establish a new connection ... 5072`，随后 `CAPTCHA 失败，换号` | solver 服务没起来，或 `TURNSTILE_SOLVER_URL` 指向了不可达地址 | `docker compose ps` 看 `solver` 是否 healthy；必要时 `docker compose logs solver`。容器内自检：`docker compose exec proxyscrape python -c "import socket;socket.create_connection(('solver',5072),3);print('ok')"` |
| `[Errno 13] Permission denied: 'keys/proxies.txt'` | 容器以 uid 10001 运行，而 `./keys` 由 Docker 以 root 创建 | 入口脚本启动时会自动修正属主；已有容器可 `sudo chown -R 10001:10001 keys && docker compose restart` |
| Web 配置页保存后，注册日志改连 `127.0.0.1:5072` | 保存配置会把空白项写入 `.env`，旧实现 `load_dotenv(override=True)` 用空值覆盖了容器注入的变量 | 已改为「空值不覆盖非空环境变量」，`.env` 留空时 compose 注入的 `http://solver:5072` 不会被覆盖 |
| `keys/` 下的文件属主变成 `root` | `docker compose exec` / `run` 默认以 root 进入容器 | 追加 `--user appuser`；或直接使用 Web 管理台触发注册（主进程固定为 10001） |
| `docker compose up` 报 `env file ... not found` | compose 的 `env_file` 指向 `.env`，首次部署尚未创建 | 先执行 `cp .env.example .env` |
| 注册成功后 `/api/accounts` 仍为空 | 账号文件在容器内写入，宿主机看的是 `./keys` | 确认 bind mount 生效：`docker compose exec proxyscrape ls -l keys` |

只有把 solver 移出 compose（例如宿主机已有独立浏览器环境）时，才需要下面的 systemd 常驻：

```ini
[Unit]
Description=Turnstile Solver
After=network-online.target

[Service]
WorkingDirectory=/opt/proxy_reg
ExecStart=/opt/proxy_reg/.venv/bin/python api_solver.py --browser_type camoufox --thread 1 --host 0.0.0.0 --port 5072
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now turnstile-solver` 后，主机重启也能自动拉起；日志用 `journalctl -u turnstile-solver -f` 查看。

### 持续集成

`.github/workflows/docker.yml` 定义两个 Job：

| 触发 | 行为 |
|------|------|
| push 到默认分支 | 运行单元测试 → 构建并推送 `latest` 与分支名标签 |
| 推送 `v*` 标签 | 同上，并附加语义化版本标签 |
| Pull Request | 仅运行测试与构建，不推送 |
| 手动触发 | 支持 `workflow_dispatch` 重新执行 |

## 临时邮箱模块

`src/mail_client.py` 不依赖本项目的注册逻辑，可作为独立的一次性邮箱客户端复用：

```python
from src.mail_client import TempMailClient

client = TempMailClient()                 # 配置默认取自环境变量
mailbox = client.create_mailbox()         # Mailbox(address="xxx@yyy")
print(mailbox.address)

code = client.wait_for_code(              # "94168d64e3" 或 None
    mailbox.address,
    timeout=150,                          # 总超时（秒）
    interval=4,                           # 轮询间隔（秒）
    should_stop=lambda: False,
    resend_after=120,                     # 超时前触发一次重发
    resend_callback=lambda: print("request resend"),
)
client.close()
```

| 方法 | 说明 |
|------|------|
| `TempMailClient(settings=None, proxies=None, log=print)` | 构造实例，配置默认读取环境变量 |
| `create_mailbox()` | 申请邮箱，返回 `Mailbox`，带最小间隔与重试保护 |
| `list_messages(address)` | 拉取收件箱（正文内联于列表响应） |
| `extract_code(text)` | 按自定义正则或内置规则提取验证码 |
| `is_target_message(msg)` | 按 `MAIL_SENDER_KEYWORDS` 过滤发件人，未配置时全部放行 |
| `wait_for_code(address, **opts)` | 轮询直到命中、超时或被 `should_stop` 中断 |
| `close()` | 释放连接 |

异常统一抛出 `TempMailError`（创建失败、正则非法等）。

## 输出文件

| 路径 | 说明 |
|------|------|
| `keys/proxies.txt` | 全部账号的代理端点，追加写入 |
| `keys/proxies_{accountId}.txt` | 按账号划分的副本，含注释行 |
| `keys/proxyscrape_accounts.txt` | 账号旁路记录，格式 `email----password----access_token` |
| `keys/account_details_cache.json` | 过期时间与流量缓存 |

`keys/` 已在 `.gitignore` 中忽略。

## 项目结构

```text
.
├── main.py                       # 注册、验证、问卷、激活试用、下载、推送
├── web_app.py                    # Web 管理台
├── download_proxies.py           # 已有账号单独下载代理
├── api_solver.py                 # 本地 Turnstile Solver
├── browser_configs.py            # 浏览器启动参数
├── db_results.py                 # 账号与会话持久化
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/docker.yml  # 测试 + 构建 + 推送镜像
├── keys/                         # 运行产物（自动创建）
├── src/
│   ├── mail_client.py            # 临时邮箱客户端
│   ├── turnstile_service.py      # Solver 调用封装
│   ├── proxyscrape_helpers.py    # 协议解析与密码生成
│   └── env_config.py             # Web 配置页字段定义与 .env 读写
└── tests/                        # 单元测试
```

## 开发

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

69 个用例全部离线运行，不发起网络请求、不写 `.env`，覆盖邮箱客户端、验证码提取、注册协议、代理解析与配置读写。

提交前的自检：

```bash
python -m py_compile main.py web_app.py src/*.py
python -m unittest discover -s tests -v
docker build -t proxy_reg:test .
```

## 常见问题

**收不到验证码**
确认 `TEMPMAIL_API_BASE` 可访问，并检查日志中 `reset-verification-code` 的返回是否成功。邮件投递较慢时，可适当调大 `MAIL_POLL_TIMEOUT`。

**收到邮件但提取不到验证码**
说明邮件格式与提取规则不匹配。可通过 `MAIL_CODE_REGEX` 指定正则；留空则使用内置的「verification code + 8–16 位十六进制」规则。

**创建邮箱较慢或返回 429**
临时邮箱免费接口有频率限制，`MAIL_GENERATE_INTERVAL` 默认 15 秒，批量注册时每个账号都会等待该间隔。

**Solver 连接失败**
compose 默认把 `TURNSTILE_SOLVER_URL` 指向内置的 `solver` 服务（`http://solver:5072`）。若改为外部 solver，需保证容器网络可达；本机直接运行 `python main.py` 时默认 `http://127.0.0.1:5072`。

**拉取镜像返回 401 或 manifest unknown**
镜像为公开包，正常情况下可直接拉取；401 通常表示包已改为私有，需要 `docker login ghcr.io`。`latest` 与分支标签仅在默认分支构建时产出，PR 构建不推送。

**Actions 中 build 未执行**
build 依赖 test，单元测试未通过时不会进入构建阶段。

**管理台提示 token 过期**
账号 JWT 约 24 小时过期，刷新或下载时自动重登（需要 Solver 可用），新 token 会回写到账号文件。

**端口被占用**
修改 `WEB_PORT`，compose 会同步调整端口映射。

## 免责声明

本项目仅供技术学习与研究，用于演示 HTTP 协议交互、临时邮箱与验证码识别的自动化实现。

- 使用本项目注册账号或领取试用，可能违反目标站点的服务条款，由此产生的账号封禁、IP 限制等后果由使用者自行承担。
- 项目不包含任何账号、令牌或密钥；所有凭据均由使用者在本地 `.env` 与 `keys/` 中自行生成与保管。
- 作者不对使用本项目造成的任何直接或间接损失负责，请勿用于商业用途或大规模滥用。

## 许可证

[MIT](LICENSE)
