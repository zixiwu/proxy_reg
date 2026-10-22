"""Unit tests for the tempmail.ing mail client (offline, no network)."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mail_client import (
    MailSettings,
    TempMailClient,
    message_content,
    message_id,
    message_sender,
)

CODE = "94168d64e3"


def _quiet_log(_message):
    pass


class TestMailSettings(unittest.TestCase):
    def test_defaults_follow_proxyscrape_format(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = MailSettings.from_env()
        self.assertEqual(settings.api_base, "https://api.tempmail.ing/api")
        # 空正则 = 使用内置的 ProxyScrape 提取规则
        self.assertEqual(settings.code_pattern, "")
        # 空关键字 = 不筛选发件人
        self.assertEqual(settings.sender_keywords, ())
        self.assertEqual(settings.poll_interval, 4.0)
        self.assertEqual(settings.poll_timeout, 150.0)
        self.assertEqual(settings.generate_interval, 15.0)
        self.assertEqual(settings.domain_blacklist, ("animatimg.com", "tempmail.ing"))

    def test_env_override(self):
        env = {
            "TEMPMAIL_API_BASE": "https://example.test/api",
            "MAIL_POLL_INTERVAL": "1.5",
            "MAIL_POLL_TIMEOUT": "30",
            "MAIL_CODE_REGEX": r"(?<!\d)([0-9a-fA-F]{8,16})\b",
            "MAIL_SENDER_KEYWORDS": "proxyscrape, noreply@proxyscrape.com",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = MailSettings.from_env()
        self.assertEqual(settings.api_base, "https://example.test/api")
        self.assertEqual(settings.poll_interval, 1.5)
        self.assertEqual(settings.poll_timeout, 30.0)
        self.assertEqual(settings.code_pattern, r"(?<!\d)([0-9a-fA-F]{8,16})\b")
        self.assertEqual(
            settings.sender_keywords, ("proxyscrape", "noreply@proxyscrape.com")
        )


class TestCodeExtraction(unittest.TestCase):
    def test_matches_verification_code_sentence(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertEqual(
            client.extract_code(f"Here is your email verification code: {CODE}"),
            CODE,
        )
        self.assertEqual(client.extract_code(f"Verification Code {CODE.upper()}"), CODE.upper())

    def test_falls_back_to_bare_hex(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertEqual(client.extract_code(f"Use {CODE} to verify"), CODE)

    def test_ignores_six_digit_numbers(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertIsNone(client.extract_code("Your order 123456 is ready"))

    def test_ignores_overlong_hex_runs(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertIsNone(client.extract_code("id 0123456789abcdef0"))

    def test_empty_content(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertIsNone(client.extract_code(""))
        self.assertIsNone(client.extract_code("no code here"))

    def test_custom_regex_overrides_default(self):
        settings = MailSettings(code_pattern=r"(?<!\d)(\d{6})(?!\d)")
        client = TempMailClient(settings=settings, log=_quiet_log)
        self.assertEqual(client.extract_code("Your code is 123456"), "123456")
        self.assertIsNone(client.extract_code(f"code {CODE}"))


class TestSenderFilter(unittest.TestCase):
    def test_default_accepts_any_sender(self):
        client = TempMailClient(settings=MailSettings(), log=_quiet_log)
        self.assertTrue(
            client.is_target_message({"from": "noreply@proxyscrape.com", "subject": "x"})
        )

    def test_keywords_filter_when_configured(self):
        settings = MailSettings(sender_keywords=("proxyscrape",))
        client = TempMailClient(settings=settings, log=_quiet_log)
        self.assertTrue(
            client.is_target_message({"from": "noreply@proxyscrape.com"})
        )
        self.assertFalse(client.is_target_message({"from": "news@other.com"}))


class TestMessageHelpers(unittest.TestCase):
    def test_message_fields(self):
        message = {
            "messageId": " x ",
            "sender": "a@b.com",
            "from_name": "A",
            "subject": "Subject",
            "text": "Body",
            "html": "<p>Html</p>",
        }
        self.assertEqual(message_id(message), "x")
        self.assertIn("a@b.com", message_sender(message))
        content = message_content(message)
        for part in ("Subject", "Body", "<p>Html</p>"):
            self.assertIn(part, content)


class _FakeClient(TempMailClient):
    """不发起网络请求的客户端，用于测试轮询逻辑。"""

    def __init__(self, messages, **kwargs):
        super().__init__(
            settings=MailSettings(poll_interval=0, poll_timeout=1),
            log=_quiet_log,
            **kwargs,
        )
        self.messages = messages

    def list_messages(self, address):
        return list(self.messages)


class TestWaitForCode(unittest.TestCase):
    def test_returns_code_from_matching_mail(self):
        message = {
            "id": "m1",
            "from": "noreply@proxyscrape.com",
            "subject": "Verify your email",
            "text": f"Here is your email verification code: {CODE}",
        }
        client = _FakeClient([message])
        self.assertEqual(client.wait_for_code("a@b.c", timeout=0.2, interval=0), CODE)

    def test_ignores_seen_ids_and_excluded_codes(self):
        messages = [
            {"id": "m1", "text": "11111111"},
            {"id": "m2", "text": f"code {CODE}"},
        ]
        client = _FakeClient(messages)
        code = client.wait_for_code(
            "a@b.c",
            timeout=0.2,
            interval=0,
            ignore_ids={"m1"},
            exclude_codes={CODE},
        )
        self.assertIsNone(code)

    def test_resend_callback_fires_once(self):
        calls = []
        client = _FakeClient([])
        code = client.wait_for_code(
            "a@b.c",
            timeout=0.3,
            interval=0.01,
            resend_after=0.05,
            resend_callback=lambda: calls.append(1),
        )
        self.assertIsNone(code)
        self.assertEqual(len(calls), 1)

    def test_stop_callback_ends_polling(self):
        client = _FakeClient([])
        self.assertIsNone(
            client.wait_for_code(
                "a@b.c", timeout=5, interval=0, should_stop=lambda: True
            )
        )


if __name__ == "__main__":
    unittest.main()
