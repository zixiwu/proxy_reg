# ProxyScrape 自动注册 + Premium 代理下载

自动完成 ProxyScrape 账号注册、邮箱验证、onboarding 问卷、激活免费试用，并把试用 Premium 代理列表下载到本地；批量全部成功后可选地把 `proxies.txt` 上传到远程订阅（Resin）。

**主产物格式**（写入 `keys/proxies.txt`，追加不覆盖）：

~~~text
protocol://user:pass@host:port
~~~

~~~text
http://s04xvtwkxqsv:3f0gsnlwbbsonwm@209.50.163.168:3129
~~~

---

## 工作流程

| 步骤 | 做什么 | 用到的接口 |
|------|--------|-----------|
| 1. 创建邮箱 | 向 tempmail.ing 申请一个一次性邮箱 | `POST {TEMPMAIL_API_BASE}/generate` |
| 2. 注册 | 带 Turnstile token 提交注册表单 | `POST /v2/v4/account/auth/register` |
| 3. 主动发信 | 让 ProxyScrape 给该邮箱发验证码 | `POST .../account/reset-verification-code` |
| 4. 收信取码 | 轮询收件箱，按正则提取验证码 | `GET {TEMPMAIL_API_BASE}/emails/{address}` |
| 5. 邮箱验证 | 提交验证码 | `POST .../account/verify-email` |
| 6. 问卷 | 完成 `/v2/typeform` 引导（纯 API，无需点页面） | `POST /v2/typeform` |
| 7. 激活试用 | `/me` 确认 `typeform=false` 后领取免费试用 | `POST .../premium/claim-trial` |
| 8. 下载代理 | 拉取该账号的试用代理列表 | `GET .../premium/proxy-list/{accountId}` |
| 9. 远程上传 | 目标数量**全部成功**后上传 | `PATCH {RESIN_SUBSCRIPTION_URL}` |

其中「创建邮箱 / 收信 / 取验证码」由本仓库的 `src/mail_client.py` 完成，**不需要任何密钥**，也不再依赖 Cloudflare Worker、GPTMail 之类的第三方邮箱服务。

---

## 快速开始

### 环境要求

- Windows / Linux / macOS，Python 3.10+（建议 3.11+）
- **Turnstile Solver**（本仓库自带 `api_solver.py`，需要浏览器依赖）
- 能访问 `https://api.tempmail.ing`（免费、无密钥）

### 1. 安装依赖

~~~bash
git clone <你的仓库地址> && cd <仓库目录>
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
python -m camoufox fetch          # Solver 需要的浏览器内核
~~~

### 2. 准备配置

~~~bash
cp .env.example .env
~~~

`.env.example` 里只有占位符，没有任何真实密钥。最少只需要关注这几项：

~~~env
# Web 管理台登录密码
WEB_PASSWORD=admin
# Turnstile Solver 地址（默认 http://127.0.0.1:5072）
TURNSTILE_SOLVER_URL=
# 注册密码：留空或填 random 表示每次随机生成
REGISTER_PASSWORD=
~~~

### 3. 启动 Turnstile Solver（另开一个终端保持运行）

~~~bash
python api_solver.py --browser_type camoufox --thread 1 --debug
~~~

默认监听 `http://0.0.0.0:5072`。Solver 没起来时注册会因为拿不到验证码 token 而失败。

### 4. 跑起来

~~~bash
# A. Web 管理台（推荐）
python web_app.py        # 浏览器打开 http://127.0.0.1:5080/

# B. 命令行批量注册
python main.py
~~~

---

## Docker 部署

镜像里包含 `main.py` / `web_app.py` / `download_proxies.py`。Turnstile Solver 依赖浏览器，建议仍然跑在宿主机，容器通过 `host.docker.internal` 访问它。

~~~bash
cp .env.example .env          # 必须存在，compose 用它注入环境变量
docker compose up --build -d  # 构建并启动 Web 管理台
# 打开 http://127.0.0.1:5080/
~~~

只跑 CLI 批量注册（不启动 Web）：

~~~bash
docker compose run --rm proxyscrape python main.py
~~~

常用命令：

~~~bash
docker compose logs -f     # 看日志
docker compose build       # 只重建镜像
docker compose down        # 停止并删除容器（keys/ 与 .env 保留在宿主机）
~~~

不用 compose 也可以：

~~~bash
docker build -t proxyscrape-register .
docker run -d --name proxyscrape \
  -p 5080:5080 --env-file .env \
  -e WEB_HOST=0.0.0.0 \
  -v "$PWD/keys:/app/keys" -v "$PWD/.env:/app/.env" \
  --add-host host.docker.internal:host-gateway \
  proxyscrape-register
~~~

**说明**

- 容器内以非 root 用户（uid 10001）运行，自带 `/api/health` 健康检查。
- `keys/` 与 `.env` 通过 bind mount 持久化，Web 配置页的修改会写回宿主机 `.env`。
- **Linux 宿主机**上 bind mount 属主是宿主机用户，可能写不进去，二选一：
  - `sudo chown -R 10001:10001 keys`（`.env` 同理）；
  - 或者在 `docker-compose.yml` 的 service 下加 `user: "${UID:-1000}:${GID:-1000}"`，用宿主机用户身份运行。

  Windows / macOS 的 Docker Desktop 一般没有这个问题。
- 镜像基于 `python:3.11-slim`，只装 `requirements.txt`，不含 camoufox / patchright 浏览器依赖。
- `PROXY` 指向宿主机端口时同样要用 `host.docker.internal`。

### 用 GitHub Actions 构建镜像

仓库自带 `.github/workflows/docker.yml`：

| 触发 | 行为 |
|------|------|
| push 到默认分支 / 打 `v*` tag / 手动 `workflow_dispatch` | 构建并推送到 GHCR（`ghcr.io/<owner>/<repo>`） |
| Pull Request | 只构建不推送（验证 Dockerfile 可用） |

首次推送后需要到 GitHub 仓库的 **Packages** 里把镜像可见性改成 public（或在使用端 `docker login ghcr.io`），否则拉取会 401。

拿到镜像后直接跑：

~~~bash
docker pull ghcr.io/<你的用户名>/<仓库名>:latest
docker run -d --name proxyscrape \
  -p 5080:5080 --env-file .env \
  -e WEB_HOST=0.0.0.0 \
  -v "$PWD/keys:/app/keys" -v "$PWD/.env:/app/.env" \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/<你的用户名>/<仓库名>:latest
~~~

---

## 配置说明（`.env`）

所有配置都可以用环境变量覆盖；Web 管理台的「配置」页也可以直接改并写回 `.env`。

### 1. 临时邮箱（tempmail.ing）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TEMPMAIL_API_BASE` | `https://api.tempmail.ing/api` | API 根地址 |
| `TEMPMAIL_SITE_ORIGIN` | `https://tempmail.ing` | 请求头 origin / referer |
| `TEMPMAIL_DURATION` | `10` | `/generate` 的 duration 参数 |
| `MAIL_CODE_REGEX` | 空 | 验证码正则；**留空**用内置规则 |
| `MAIL_SENDER_KEYWORDS` | 空 | 发件人/主题关键字，逗号分隔；空表示不筛选 |
| `MAIL_POLL_INTERVAL` | `4` | 收信轮询间隔（秒） |
| `MAIL_POLL_TIMEOUT` | `150` | 收信总超时（秒） |
| `MAIL_REQUEST_TIMEOUT` | `15` | 单次 HTTP 请求超时（秒） |
| `MAIL_GENERATE_INTERVAL` | `15` | 两次创建邮箱的最小间隔（秒，防止触发限流） |
| `MAIL_GENERATE_RETRIES` | `3` | 创建邮箱失败重试次数 |
| `MAIL_GENERATE_BACKOFF` | `10` | 重试退避基数（秒） |
| `MAIL_RATE_LIMIT_WAIT` | `5` | 遇到 429 的额外等待（秒） |
| `MAIL_DOMAIN_BLACKLIST` | `animatimg.com,tempmail.ing` | 跳过这些域名（收到的不是信） |
| `MAIL_BLACKLIST_RETRIES` | `5` | 命中黑名单时重新申请邮箱的次数 |

**内置验证码规则**（`MAIL_CODE_REGEX` 留空时按顺序尝试）：

1. `(?:email\s+)?verification\s+code\s*[:：]?\s*([0-9a-fA-F]{8,16})\b` —— 匹配 “verification code: 94168d64e3” 这类句式；
2. `(?<![0-9a-fA-F])([0-9a-fA-F]{8,16})(?![0-9a-fA-F])` —— 兜底取正文里孤立的 8~16 位十六进制串。

ProxyScrape 的验证码就是 8~16 位十六进制。换站点时可以自己写正则，例如 6 位数字：

~~~env
MAIL_CODE_REGEX=(?<!\d)(\d{6})(?!\d)
~~~

其他行为：

- 收到验证码前会先调用 `reset-verification-code` 主动发信；**120 秒**还没收到会自动再发一次。
- 邮箱请求**不走** `PROXY`，始终直连（避免代理出口被邮箱服务判定风控）。
- 已处理的邮件 id 会被忽略，可避免重复使用同一个验证码。

### 2. 注册参数

~~~env
# 固定密码，或 random（留空）每次随机；需满足 ≥8 位 + 大写 + 数字 + 特殊字符
REGISTER_PASSWORD=
# 两次注册之间的最小间隔（秒），0 表示不限制
REGISTER_INTERVAL=5
# 非交互指定注册数量（也可以交互输入或用管道）
REGISTER_COUNT=5
# 下载代理时的协议模板
PROXY_DOWNLOAD_PROTOCOL=http
# 给 curl_cffi 用的 HTTP 代理（可选）
PROXY=
# Turnstile 连续失败多少轮后放弃该账号
MAX_CAPTCHA_FAIL_ROUNDS=3
~~~

### 3. Turnstile

~~~env
# 留空默认 http://127.0.0.1:5072；分机部署填 Solver 机器地址
TURNSTILE_SOLVER_URL=
~~~

调用方式：

- `GET {TURNSTILE_SOLVER_URL}/turnstile?url=...&sitekey=...` → `taskId`
- `GET {TURNSTILE_SOLVER_URL}/result?id=...` → token

Solver 与注册机可以分机部署：A 机器跑 `api_solver.py --host 0.0.0.0 --port 5072`（防火墙只放行内网），B 机器把 `TURNSTILE_SOLVER_URL` 指向 A。

### 4. Resin 远程上传（可选）

~~~env
RESIN_SUBSCRIPTION_URL=https://resin.example.com/api/v1/subscriptions/<订阅UUID>
RESIN_API_TOKEN=<Bearer 令牌>
RESIN_NAME=ProxyScrape
RESIN_UPDATE_INTERVAL=12h
RESIN_EPHEMERAL_NODE_EVICT_DELAY=72h0m0s
RESIN_ENABLED=true
RESIN_EPHEMERAL=false
RESIN_INCREMENTAL_ALIVE_NODES=false
~~~

未配置 `RESIN_SUBSCRIPTION_URL` / `RESIN_API_TOKEN` 时跳过上传，本地文件照常保存。

### 5. Web 管理台

~~~env
WEB_HOST=127.0.0.1     # Docker 内需改成 0.0.0.0
WEB_PORT=5080
WEB_PASSWORD=admin     # 登录密码，生产环境请改
~~~

---

## 使用说明

### CLI 批量注册

~~~bash
python main.py
# 或非交互
REGISTER_COUNT=5 python main.py
echo 5 | python main.py
~~~

流程日志大致为：

~~~text
[*] 临时邮箱 API: https://api.tempmail.ing/api
[*] 开始 ProxyScrape 注册: xxx@domain
[*] 求解 Turnstile ...
[+] 注册 API 成功
[*] 开始邮箱验证流程...
[*] xxx@domain 请求发送邮箱验证码 (reset-verification-code)...
[*] xxx@domain 收到验证邮件，验证码 94168d64e3
[+] 邮箱验证成功
[*] 开始 onboarding 问卷 ...
[+] 问卷完成
[*] 激活 Premium 免费试用...
[+] Premium 免费试用已激活
[✓] 代理下载成功: ... | 100 条
~~~

### Web 管理台

~~~bash
python web_app.py
~~~

浏览器打开 **http://127.0.0.1:5080/**，首次会跳转 `/login`。登录后配置页所有字段明文显示。

| 页面 / 接口 | 说明 |
|-------------|------|
| `/login` | 登录页 |
| `/` | 管理首页：账号表、批量注册、注册日志、下载 / 删除 |
| `/config` | 配置页：读写 `.env` 并热更新运行参数 |
| `POST /api/auth/login` | `{"password":"..."}` 登录 |
| `POST /api/auth/logout` | 退出 |
| `GET /api/accounts` | 账号列表（`?live=1` 刷新详情） |
| `POST /api/accounts/refresh` | 刷新单个账号；JWT 过期时自动重登并写回 token |
| `GET /api/accounts/download-proxies?email=` | 下载该账号代理文本 |
| `GET /api/proxies/download-all` | 下载全部代理 |
| `POST /api/proxies/upload-resin` | `{"live":true}` 上传到 Resin |
| `POST /api/accounts/delete` / `delete-all` | 删除账号 / 清空 |
| `POST /api/register` | `{"count":N}` 启动注册 |
| `GET /api/register/status` / `/api/register/logs?since=N` | 注册状态 / 增量日志 |
| `GET /api/health` | 健康检查（公开） |
| `GET` / `POST /api/config` | 读写配置 |

表格字段：邮箱、剩余到期（实时倒计时）、流量剩余、代理数、类型、状态。
ProxyScrape 的 JWT 约 24 小时过期，过期后点「刷新」或「下载」会自动重登（需要可用的 Solver）；刷新结果会缓存到 `keys/account_details_cache.json`。

### 已有账号单独下载代理

~~~bash
python download_proxies.py                 # 用账号文件最后一行
python download_proxies.py --all           # 全部账号
python download_proxies.py --token <JWT> --account-id <UUID>
python download_proxies.py --protocol http
~~~

### 手动上传 Resin

~~~bash
python -c "from main import upload_proxies_to_resin; print(upload_proxies_to_resin())"
~~~

---

## 临时邮箱模块（可独立复用）

`src/mail_client.py` 不依赖本项目的注册逻辑，可以单独用来做“临时邮箱收验证码”：

~~~python
from src.mail_client import TempMailClient

client = TempMailClient()                      # 从环境变量读配置
mailbox = client.create_mailbox()              # -> Mailbox(address="xxx@yyy")
print(mailbox.address)

code = client.wait_for_code(                   # -> "94168d64e3" 或 None
    mailbox.address,
    timeout=150,          # 总超时（秒）
    interval=4,           # 轮询间隔（秒）
    should_stop=lambda: False,
    resend_after=120,     # 120s 仍未收到时调用一次下面的回调
    resend_callback=lambda: print("让目标站点重新发信"),
)
client.close()
~~~

主要接口：

| 方法 | 说明 |
|------|------|
| `TempMailClient(settings=None, proxies=None, log=print)` | 构造，配置默认取环境变量 |
| `create_mailbox()` | 申请邮箱，返回 `Mailbox`；受最小间隔与重试保护 |
| `list_messages(address)` | 拉取收件箱（邮件正文已内联在列表响应里） |
| `extract_code(text)` | 按正则 / 内置规则提取验证码 |
| `is_target_message(msg)` | 按 `MAIL_SENDER_KEYWORDS` 过滤发件人；未配置则全放行 |
| `wait_for_code(address, **opts)` | 轮询直到出码、超时或被 `should_stop` 中断 |
| `close()` | 释放连接 |

出错时抛 `TempMailError`（创建失败、正则非法等）。

---

## 输出文件

| 路径 | 说明 |
|------|------|
| `keys/proxies.txt` | **主产物**，所有账号代理追加写入 |
| `keys/proxies_{accountId}.txt` | 按子账号追加的副本（含注释行） |
| `keys/proxyscrape_accounts.txt` | 账号旁路记录 `email----password----access_token` |
| `keys/account_details_cache.json` | Web 管理台的到期 / 流量缓存 |

---

## 目录结构

~~~text
.
├── main.py                 # 注册 + 验证 + 问卷 + 激活试用 + 下载 + 远程上传
├── web_app.py              # Web 管理台
├── download_proxies.py     # 用已有账号单独下载代理
├── api_solver.py           # 本地 Turnstile Solver
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── requirements.txt
├── .github/workflows/docker.yml   # 自动构建并推送镜像
├── keys/                   # 产物目录（运行时生成）
├── src/
│   ├── mail_client.py      # tempmail.ing：创建邮箱 / 收信 / 取验证码
│   ├── turnstile_service.py
│   ├── proxyscrape_helpers.py
│   └── env_config.py       # Web 配置页的字段定义与 .env 读写
└── tests/
    ├── test_mail_client.py
    ├── test_proxyscrape_helpers.py
    ├── test_env_config.py
    ├── test_premium_trial_claim.py
    └── test_account_web_helpers.py
~~~

---

## 开发与测试

~~~bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
~~~

单测全部离线运行（不联网、不写 `.env`），覆盖邮箱模块的配置解析 / 验证码提取 / 轮询行为，以及注册协议、代理解析、配置读写等纯函数。

---

## 常见问题

**收不到验证码？**
先确认 `TEMPMAIL_API_BASE` 可访问（`curl -s https://api.tempmail.ing/api/emails/x` 有 JSON 返回即可），再确认 ProxyScrape 侧确实发了信（日志里 `reset-verification-code` 的返回）。可以临时把 `MAIL_POLL_TIMEOUT` 调大，或把 `MAIL_POLL_INTERVAL` 调小。

**收到了信但一直解析不到验证码？**
说明邮件格式和提取规则不匹配。把 `MAIL_CODE_REGEX` 设成与该站点邮件对应的正则；留空则使用内置的“verification code: <8~16 位十六进制>”规则。

**创建邮箱很慢 / 报 429？**
tempmail.ing 免费接口有频率限制，`MAIL_GENERATE_INTERVAL` 默认 15 秒，批量注册时每个账号都会等这么久，属正常现象。

**Solver 连不上？**
`TURNSTILE_SOLVER_URL` 默认 `http://127.0.0.1:5072`，容器里要改成 `http://host.docker.internal:5072`；分机部署检查防火墙。

**管理台一直显示 token 过期？**
ProxyScrape JWT 约 24 小时过期，点「刷新」会自动重登（需要 Solver 可用），新 token 会写回 `keys/proxyscrape_accounts.txt`。

**5080 端口被占用？**
改 `WEB_PORT`（Docker 下 compose 会同步映射端口）。
