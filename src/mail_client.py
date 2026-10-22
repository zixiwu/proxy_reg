"""
tempmail.ing 临时邮箱客户端（移植自可用的 o.py）。

对外只暴露两个动作：

    client = TempMailClient()
    mailbox = client.create_mailbox()            # 创建邮箱 -> Mailbox(address=...)
    code = client.wait_for_code(mailbox.address) # 等待并获取验证码 -> "123456" 或 None

实现与 o.py 保持一致：
  - POST {api_base}/generate            （带 15s 最小调用间隔、429/异常重试、域名黑名单跳过）
  - GET  {api_base}/emails/{address}    （邮件列表，正文内联在列表响应里，无需单独读信）
  - 轮询收件箱，按正则提取验证码，支持忽略已见邮件 / 排除已用验证码

验证码格式按本仓库（ProxyScrape）的邮件：8–16 位十六进制，见 DEFAULT_CODE_PATTERNS。
所有可变参数都从环境变量读取（见 MailSettings.from_env），未配置时使用下面的默认值。
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from curl_cffi import requests as curl_requests


# 未设置 MAIL_CODE_REGEX 时使用的内置提取规则（按 ProxyScrape 邮件格式）。
# 先按 "verification code: <hex>" 这样的上下文取，取不到再回退到孤立的十六进制串。
DEFAULT_CODE_PATTERNS = (
    r"(?:email\s+)?verification\s+code\s*[:：]?\s*([0-9a-fA-F]{8,16})\b",
    r"(?<![0-9a-fA-F])([0-9a-fA-F]{8,16})(?![0-9a-fA-F])",
)


class TempMailError(RuntimeError):
    """临时邮箱不可用（创建失败 / 配置错误）。"""


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = _env_float(name, float(default))
    return max(1, int(value))


def _env_list(name: str, default: Iterable[str]) -> tuple:
    """逗号分隔的环境变量；显式设为空串表示空列表，未设置时用 default。"""
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    return tuple(item.strip() for item in raw.replace(";", ",").split(",") if item.strip())


@dataclass(frozen=True)
class MailSettings:
    """邮箱服务配置（全部来自环境变量，默认值与 o.py 一致）。"""

    # --- API 地址 ---
    api_base: str = "https://api.tempmail.ing/api"
    site_origin: str = "https://tempmail.ing"
    # /generate 的邮箱有效期参数（o.py 固定传 10）
    duration: int = 10
    # 单次 HTTP 请求超时（秒）
    request_timeout: float = 15.0
    # curl_cffi 浏览器指纹
    impersonate: str = "chrome"

    # --- /generate 速率控制与重试 ---
    generate_interval: float = 15.0
    generate_retries: int = 3
    generate_backoff: float = 10.0
    rate_limit_wait: float = 5.0

    # --- 收件箱轮询 ---
    poll_interval: float = 4.0
    poll_timeout: float = 150.0

    # --- 验证码与邮件过滤 ---
    # 为空时使用 DEFAULT_CODE_PATTERNS（ProxyScrape 的 8–16 位十六进制）
    code_pattern: str = ""
    # 为空表示不筛选发件人（单账号单邮箱，无需过滤）
    sender_keywords: tuple = ()

    # --- 域名黑名单（被目标站点封禁的临时邮箱域名）---
    domain_blacklist: tuple = ("animatimg.com", "tempmail.ing")
    blacklist_retries: int = 5

    @classmethod
    def from_env(cls) -> "MailSettings":
        return cls(
            api_base=_env_str("TEMPMAIL_API_BASE", cls.api_base).rstrip("/"),
            site_origin=_env_str("TEMPMAIL_SITE_ORIGIN", cls.site_origin).rstrip("/"),
            duration=_env_int("TEMPMAIL_DURATION", cls.duration),
            request_timeout=_env_float("MAIL_REQUEST_TIMEOUT", cls.request_timeout),
            impersonate=_env_str("MAIL_IMPERSONATE", cls.impersonate),
            generate_interval=_env_float("MAIL_GENERATE_INTERVAL", cls.generate_interval),
            generate_retries=_env_int("MAIL_GENERATE_RETRIES", cls.generate_retries),
            generate_backoff=_env_float("MAIL_GENERATE_BACKOFF", cls.generate_backoff),
            rate_limit_wait=_env_float("MAIL_RATE_LIMIT_WAIT", cls.rate_limit_wait),
            poll_interval=_env_float("MAIL_POLL_INTERVAL", cls.poll_interval),
            poll_timeout=_env_float("MAIL_POLL_TIMEOUT", cls.poll_timeout),
            code_pattern=_env_str("MAIL_CODE_REGEX", cls.code_pattern),
            sender_keywords=_env_list("MAIL_SENDER_KEYWORDS", cls.sender_keywords),
            domain_blacklist=_env_list("MAIL_DOMAIN_BLACKLIST", cls.domain_blacklist),
            blacklist_retries=_env_int("MAIL_BLACKLIST_RETRIES", cls.blacklist_retries),
        )


@dataclass(frozen=True)
class Mailbox:
    """创建成功的临时邮箱。token 目前为空，仅为兼容旧接口而保留。"""

    address: str
    token: str = ""


def message_id(message: Dict[str, Any]) -> str:
    return str(message.get("id") or message.get("messageId") or "").strip()


def message_sender(message: Dict[str, Any]) -> str:
    return " ".join(
        str(part or "").strip()
        for part in [
            message.get("from"),
            message.get("sender"),
            message.get("from_address"),
            message.get("from_name"),
        ]
        if str(part or "").strip()
    )


def message_content(message: Dict[str, Any]) -> str:
    """正文在列表响应内联返回，o.py 直接把这几段拼起来再跑正则。"""
    return "\n".join(
        str(part or "")
        for part in [
            message.get("subject"),
            message.get("text"),
            message.get("content"),
            message.get("body"),
            message.get("html"),
        ]
        if str(part or "")
    )


def _is_tls_error(exc: Exception) -> bool:
    text = str(exc)
    return "TLS" in text or "SSL" in text or "curl" in text.lower()


class _RetrySession:
    """curl_cffi Session + TLS 握错快速重试（与 o.py 一致，间隔 0.5s 递增）。"""

    def __init__(self, impersonate: str, retries: int = 3) -> None:
        self._session = curl_requests.Session()
        self._impersonate = impersonate
        self._retries = retries

    def request(self, method: str, url: str, **kwargs):
        kwargs.setdefault("impersonate", self._impersonate)
        for attempt in range(1, self._retries + 1):
            try:
                return getattr(self._session, method)(url, **kwargs)
            except Exception as exc:
                if _is_tls_error(exc) and attempt < self._retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise
        raise TempMailError("请求重试次数已用尽")

    def get(self, url: str, **kwargs):
        return self.request("get", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("post", url, **kwargs)

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


class TempMailClient:
    """tempmail.ing 邮箱：创建邮箱、拉取收件箱、等待验证码。"""

    def __init__(
        self,
        settings: Optional[MailSettings] = None,
        *,
        proxies: Optional[Dict[str, str]] = None,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.settings = settings or MailSettings.from_env()
        self.proxies = proxies
        self.log = log or print
        self._http = _RetrySession(self.settings.impersonate)
        self._generate_lock = threading.Lock()
        self._last_generate_ts = 0.0
        patterns = (
            (self.settings.code_pattern.strip(),)
            if self.settings.code_pattern.strip()
            else DEFAULT_CODE_PATTERNS
        )
        try:
            self._code_res = tuple(re.compile(pattern) for pattern in patterns)
        except re.error as exc:
            raise TempMailError(f"MAIL_CODE_REGEX 不是合法正则: {exc}") from exc

    # ------------------------------------------------------------------ API
    def _generate_headers(self) -> Dict[str, str]:
        return {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": self.settings.site_origin,
            "referer": f"{self.settings.site_origin}/",
        }

    def _inbox_headers(self) -> Dict[str, str]:
        return {"accept": "*/*", "referer": f"{self.settings.site_origin}/"}

    def _request_generate(self) -> Dict[str, Any]:
        """带速率限制与重试的 /generate 调用，失败返回空 dict。"""
        settings = self.settings
        for attempt in range(1, settings.generate_retries + 1):
            with self._generate_lock:
                wait = settings.generate_interval - (time.monotonic() - self._last_generate_ts)
                if wait > 0:
                    time.sleep(wait)
                self._last_generate_ts = time.monotonic()

            try:
                resp = self._http.post(
                    f"{settings.api_base}/generate",
                    headers=self._generate_headers(),
                    json={"duration": settings.duration},
                    proxies=self.proxies,
                    timeout=settings.request_timeout,
                )

                if resp.status_code == 429:
                    retry_after = settings.rate_limit_wait + settings.generate_backoff * attempt
                    self.log(
                        f"[!] tempmail /generate 限流，{int(retry_after)}s 后重试 "
                        f"({attempt}/{settings.generate_retries})"
                    )
                    time.sleep(retry_after)
                    continue

                try:
                    data = resp.json()
                except Exception:
                    data = {}

                if resp.status_code == 200 and isinstance(data, dict) and data.get("success"):
                    address = str((data.get("email") or {}).get("address") or "").strip()
                    self.log(f"[*] tempmail /generate 成功: {address or '<empty>'}")
                    return data

                self.log(
                    f"[!] tempmail /generate 失败: status={resp.status_code} "
                    f"body={str(resp.text)[:150]}"
                )
            except Exception as exc:
                self.log(f"[!] tempmail /generate 异常: attempt={attempt} error={exc}")

            if attempt < settings.generate_retries:
                backoff = settings.generate_backoff * attempt
                self.log(f"[*] tempmail /generate 准备重试: backoff={int(backoff)}s")
                time.sleep(backoff)

        return {}

    def create_mailbox(self) -> Mailbox:
        """创建临时邮箱；连续命中黑名单域名或接口失败时抛 TempMailError。"""
        settings = self.settings
        for attempt in range(1, settings.blacklist_retries + 1):
            data = self._request_generate()
            if not data:
                raise TempMailError("tempmail 创建邮箱失败：已用尽重试")

            address = str((data.get("email") or {}).get("address") or "").strip()
            if not address:
                raise TempMailError("tempmail /generate 响应缺少 email.address")

            domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
            if domain in settings.domain_blacklist:
                self.log(
                    f"[!] 命中邮箱域名黑名单: {domain} "
                    f"({attempt}/{settings.blacklist_retries})"
                )
                continue

            self.log(f"[*] 临时邮箱可用: {address}")
            return Mailbox(address=address)

        raise TempMailError(
            f"连续 {settings.blacklist_retries} 次命中黑名单域名，放弃创建邮箱"
        )

    def list_messages(self, address: str) -> List[Dict[str, Any]]:
        """获取收件箱邮件列表（正文已内联）。非 200 视为空收件箱。"""
        if not address:
            return []
        resp = self._http.get(
            f"{self.settings.api_base}/emails/{urllib.parse.quote(address, safe='')}",
            headers=self._inbox_headers(),
            proxies=self.proxies,
            timeout=self.settings.request_timeout,
        )
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        messages = (data or {}).get("emails") if isinstance(data, dict) else None
        if not isinstance(messages, list):
            return []
        return [item for item in messages if isinstance(item, dict)]

    # --------------------------------------------------------------- 提取
    def extract_code(self, content: str) -> Optional[str]:
        """从邮件正文中提取验证码：MAIL_CODE_REGEX 优先，未配置时用内置规则。"""
        if not content:
            return None
        for pattern in self._code_res:
            for match in pattern.finditer(content):
                groups = match.groups() or (match.group(0),)
                for group in groups:
                    if group:
                        return str(group).strip()
        return None

    def is_target_message(self, message: Dict[str, Any]) -> bool:
        """MAIL_SENDER_KEYWORDS 为空时不筛选；否则任一关键字命中即视为目标邮件。"""
        keywords = self.settings.sender_keywords
        if not keywords:
            return True
        haystack = f"{message_sender(message)}\n{message_content(message)}".lower()
        return any(keyword.lower() in haystack for keyword in keywords)

    # --------------------------------------------------------------- 轮询
    def wait_for_code(
        self,
        address: str,
        *,
        timeout: Optional[float] = None,
        interval: Optional[float] = None,
        ignore_ids: Optional[Iterable[str]] = None,
        exclude_codes: Optional[Iterable[str]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        resend_after: Optional[float] = None,
        resend_callback: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """轮询收件箱直到拿到验证码；超时返回 None。

        resend_after/resend_callback: 开始轮询 N 秒后仍无验证码时，补发一次邮件。
        should_stop: 返回 True 时提前结束（用于 Ctrl+C / Web 停止）。
        """
        settings = self.settings
        wait_timeout = settings.poll_timeout if timeout is None else max(0.0, timeout)
        poll_interval = settings.poll_interval if interval is None else max(0.0, interval)
        deadline = time.monotonic() + wait_timeout

        seen_ids = {str(item) for item in (ignore_ids or ()) if str(item)}
        excluded = {str(item) for item in (exclude_codes or ()) if str(item)}

        resend_deadline: Optional[float] = None
        if resend_callback is not None and resend_after:
            resend_deadline = time.monotonic() + resend_after

        self.log(
            f"[*] 开始轮询验证码: {address} (timeout={int(wait_timeout)}s "
            f"interval={poll_interval:g}s)"
        )

        round_no = 0
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                self.log("[!] 轮询被停止")
                return None

            round_no += 1
            try:
                messages = self.list_messages(address)
            except Exception as exc:
                self.log(f"[!] 收件箱轮询异常: {type(exc).__name__}: {exc}")
                messages = []

            for message in messages:
                mid = message_id(message)
                if mid and mid in seen_ids:
                    continue
                if mid:
                    seen_ids.add(mid)

                if not self.is_target_message(message):
                    continue

                code = self.extract_code(message_content(message))
                if not code:
                    self.log(
                        f"[!] 目标邮件未解析到验证码: id={mid or '<no-id>'} "
                        f"subject={str(message.get('subject') or '')[:80]}"
                    )
                    continue
                if code in excluded:
                    self.log(f"[!] 跳过已排除验证码: {code}")
                    continue

                self.log(f"[+] 已获取验证码: {code}")
                return code

            if round_no % 5 == 0:
                self.log(f"[*] 等待验证邮件... ({round_no})")

            if resend_deadline is not None and time.monotonic() >= resend_deadline:
                resend_deadline = None
                try:
                    resend_callback()  # type: ignore[misc]
                except Exception as exc:
                    self.log(f"[!] 补发验证码失败: {exc}")

            time.sleep(poll_interval)

        self.log(f"[-] 验证码轮询超时: {address} ({int(wait_timeout)}s)")
        return None

    def close(self) -> None:
        self._http.close()
