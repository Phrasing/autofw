import asyncio
import email
import html
import imaplib
import random
import re
from dataclasses import dataclass
from email.header import decode_header


@dataclass(frozen=True)
class GmailConfig:
    email: str
    app_password: str
    max_connections: int = 3
    imap_timeout: int = 15


class GmailClient:
    def __init__(self, config: GmailConfig):
        self.config = config
        self._semaphore = asyncio.Semaphore(config.max_connections)

    async def _jittered_sleep(self, base_interval: int) -> float:
        """Sleep with jitter to prevent thundering herd in concurrent scenarios."""
        jitter = random.uniform(-2, 2)
        interval = max(1, base_interval + jitter)
        await asyncio.sleep(interval)
        return interval

    def _connect(self) -> imaplib.IMAP4_SSL:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=self.config.imap_timeout)
        mail.login(self.config.email, self.config.app_password)
        return mail

    def _extract_code_from_subject(self, subject: str, pattern: re.Pattern) -> str | None:
        match = pattern.search(subject)
        return match.group(1) if match else None

    def _decode_subject(self, msg: email.message.Message) -> str:
        decoded_parts = decode_header(msg.get("Subject", ""))
        return "".join(
            part.decode(enc or "utf-8", errors="ignore") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )

    def _get_email_body(self, msg: email.message.Message) -> str:
        """Extract and decode email body content."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body += payload.decode(charset, errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="ignore")
        # Unescape HTML entities (e.g., &amp; -> &)
        body = html.unescape(body)
        return body

    def _extract_link_from_body(self, body: str, pattern: re.Pattern) -> str | None:
        """Extract a link from email body using pattern."""
        # First try to extract href values from HTML anchor tags
        href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        for href_match in href_pattern.finditer(body):
            href = href_match.group(1)
            if pattern.search(href):
                return href
        # Fallback to direct pattern search in body
        match = pattern.search(body)
        return match.group(0) if match else None

    def _get_all_links(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        """Get all links matching pattern from email bodies."""
        mail = self._connect()
        links: list[str] = []
        try:
            mail.select('"[Gmail]/All Mail"')
            search_query = f'TO "{target_email}"'
            if sender_filter:
                search_query = f'(FROM "{sender_filter}" {search_query})'
            _, message_numbers = mail.search(None, search_query)
            if not message_numbers[0]:
                return links
            all_nums = message_numbers[0].split()
            for num in reversed(all_nums[-limit:] if len(all_nums) > limit else all_nums):
                _, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        body = self._get_email_body(msg)
                        link = self._extract_link_from_body(body, pattern)
                        if link and link not in links:
                            links.append(link)
            return links
        finally:
            mail.logout()

    def _get_all_codes(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        mail = self._connect()
        codes: list[str] = []
        try:
            mail.select('"[Gmail]/All Mail"')
            search_query = f'TO "{target_email}"'
            if sender_filter:
                search_query = f'(FROM "{sender_filter}" {search_query})'
            _, message_numbers = mail.search(None, search_query)
            if not message_numbers[0]:
                return codes
            all_nums = message_numbers[0].split()
            for num in reversed(all_nums[-limit:] if len(all_nums) > limit else all_nums):
                _, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        code = self._extract_code_from_subject(self._decode_subject(msg), pattern)
                        if code and code not in codes:
                            codes.append(code)
            return codes
        finally:
            mail.logout()

    async def _fetch_codes(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
        limit: int = 10,
        timeout: int = 30,
    ) -> list[str]:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._get_all_codes, target_email, pattern, sender_filter, limit),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return []

    async def get_existing_codes(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
    ) -> set[str]:
        return set(await self._fetch_codes(target_email, pattern, sender_filter, 10))

    async def wait_for_code(
        self,
        target_email: str,
        pattern: re.Pattern,
        timeout: int = 120,
        poll_interval: int = 5,
        existing_codes: set[str] | None = None,
        sender_filter: str | None = None,
    ) -> str:
        """Wait for a new verification code, raises TimeoutError if not found."""
        if existing_codes is None:
            existing_codes = await self.get_existing_codes(target_email, pattern, sender_filter)
        elapsed = 0.0
        while elapsed < timeout:
            elapsed += await self._jittered_sleep(poll_interval)
            for code in await self._fetch_codes(target_email, pattern, sender_filter, 5):
                if code not in existing_codes:
                    return code
        raise TimeoutError(f"No verification code received for {target_email} within {timeout}s")

    async def wait_for_code_optional(
        self,
        target_email: str,
        pattern: re.Pattern,
        timeout: int = 25,
        poll_interval: int = 5,
        existing_codes: set[str] | None = None,
        sender_filter: str | None = None,
    ) -> str | None:
        """Wait for a new verification code, returns None if not found."""
        if existing_codes is None:
            existing_codes = await self.get_existing_codes(target_email, pattern, sender_filter)
        elapsed = 0.0
        while elapsed < timeout:
            elapsed += await self._jittered_sleep(poll_interval)
            for code in await self._fetch_codes(target_email, pattern, sender_filter, 5):
                if code not in existing_codes:
                    return code
        return None

    async def _fetch_links(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
        limit: int = 10,
        timeout: int = 30,
    ) -> list[str]:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._get_all_links, target_email, pattern, sender_filter, limit),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return []

    async def get_existing_links(
        self,
        target_email: str,
        pattern: re.Pattern,
        sender_filter: str | None = None,
    ) -> set[str]:
        return set(await self._fetch_links(target_email, pattern, sender_filter, 10))

    async def wait_for_link(
        self,
        target_email: str,
        pattern: re.Pattern,
        timeout: int = 120,
        poll_interval: int = 5,
        existing_links: set[str] | None = None,
        sender_filter: str | None = None,
    ) -> str | None:
        """Wait for a new verification link from email body, returns None if not found."""
        if existing_links is None:
            existing_links = await self.get_existing_links(target_email, pattern, sender_filter)
        elapsed = 0.0
        while elapsed < timeout:
            elapsed += await self._jittered_sleep(poll_interval)
            for link in await self._fetch_links(target_email, pattern, sender_filter, 5):
                if link not in existing_links:
                    return link
        return None
