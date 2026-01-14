import asyncio
import re
from enum import Enum, auto

from autofw.browser import Browser
from autofw.email import GmailClient


class ToppsState(Enum):
    """States for the Topps account creation flow."""

    INIT = auto()
    HOMEPAGE = auto()
    CF_CHECK_1 = auto()
    LOGIN_PAGE = auto()
    CF_CHECK_2 = auto()
    EMAIL_ENTRY = auto()
    CONTINUE_CLICKED = auto()
    REGISTRATION_FORM = auto()
    FORM_SUBMITTED = auto()
    WAITING_EMAIL = auto()
    VERIFICATION_LINK = auto()
    COMPLETE = auto()
    FAILED = auto()


# URL patterns for validating each state
STATE_VALIDATORS = {
    ToppsState.HOMEPAGE: lambda url: "topps.com" in url,
    ToppsState.LOGIN_PAGE: lambda url: "id.fanatics.com" in url or "account/login" in url,
    ToppsState.EMAIL_ENTRY: lambda url: "id.fanatics.com" in url,
    ToppsState.REGISTRATION_FORM: lambda url: "id.fanatics.com" in url,
    ToppsState.VERIFICATION_LINK: lambda url: "verify-email" in url,
}


class ToppsAccountGenerator(Browser):
    TOPPS_URL = "https://www.topps.com/"
    FANATICS_SENDER = "no-reply@t.one.fan"
    VERIFY_LINK_PATTERN = re.compile(r"https://[^\s\"'<>]+verify-email[^\s\"'<>]+token=[^\s\"'<>]+")

    def __init__(self, config=None, instance_id: int = 0):
        super().__init__(config)
        self.instance_id = instance_id
        self.state = ToppsState.INIT

    def _log(self, msg: str):
        """Print with instance ID prefix for concurrent logging."""
        print(f"[{self.instance_id}] {msg}")

    async def _is_cf_challenge_present(self) -> bool:
        """Check if Cloudflare challenge is still on the page."""
        cf_indicators = [
            "#challenge-running",
            "#challenge-stage",
            "iframe[src*='challenges.cloudflare.com']",
        ]
        for selector in cf_indicators:
            try:
                elem = await asyncio.wait_for(self.tab.select(selector), timeout=1)
                if elem:
                    return True
            except Exception:
                pass
        return False

    async def _verify_cf_with_retry(self, max_attempts: int = 3) -> bool:
        """Verify Cloudflare with retry logic."""
        for attempt in range(max_attempts):
            try:
                await self.tab.verify_cf()
                await self.delay("page")

                # Check if CF challenge is still present
                if await self._is_cf_challenge_present():
                    self._log(f"      CF still present, retrying ({attempt + 1}/{max_attempts})...")
                    await asyncio.sleep(2)
                    continue
                return True
            except Exception as e:
                self._log(f"      CF verification error: {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2)
        return False

    async def _validate_state(self, state: ToppsState) -> bool:
        """Validate current page matches expected state."""
        validator = STATE_VALIDATORS.get(state)
        if validator is None:
            return True  # No validation needed

        current_url = self.tab.target.url
        return validator(current_url)

    async def _transition_to(
        self,
        target_state: ToppsState,
        action,
        max_retries: int = 2,
    ) -> bool:
        """Execute action and validate we reached the target state."""
        for attempt in range(max_retries + 1):
            try:
                await action()
                await self.delay("short")

                # Validate we're in the expected state
                if await self._validate_state(target_state):
                    self.state = target_state
                    return True

                self._log(
                    f"      State validation failed for {target_state.name}, retry {attempt + 1}/{max_retries + 1}"
                )
            except Exception as e:
                self._log(f"      Action failed: {e}, retry {attempt + 1}/{max_retries + 1}")

            if attempt < max_retries:
                await asyncio.sleep(2)

        return False

    async def create_account(
        self,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        email_client: GmailClient,
    ) -> tuple[bool, str]:
        """Create a Topps account and verify via email link."""
        self.state = ToppsState.INIT

        try:
            # Get existing verification links before registration
            existing_links = await email_client.get_existing_links(
                email, self.VERIFY_LINK_PATTERN, self.FANATICS_SENDER
            )

            # State: HOMEPAGE
            self._log("[1/6] Navigating to Topps...")
            if not await self._transition_to(
                ToppsState.HOMEPAGE,
                lambda: self.navigate("https://www.topps.com/"),
            ):
                return False, f"Failed to load homepage (state: {self.state.name})"

            # State: CF_CHECK_1
            self._log("      Checking for Cloudflare...")
            if not await self._verify_cf_with_retry():
                return False, "Cloudflare verification failed on homepage"
            self.state = ToppsState.CF_CHECK_1

            # State: LOGIN_PAGE
            self._log("[2/6] Going to login page...")
            if not await self._transition_to(
                ToppsState.LOGIN_PAGE,
                lambda: self.navigate("https://www.topps.com/customer/account/login"),
            ):
                return False, f"Failed to load login page (state: {self.state.name})"

            await self.delay("page")  # Extra wait for redirects

            # State: CF_CHECK_2
            self._log("      Checking for Cloudflare...")
            if not await self._verify_cf_with_retry():
                return False, "Cloudflare verification failed on login"
            self.state = ToppsState.CF_CHECK_2

            self._log(f"      Current URL: {self.tab.target.url}")

            # State: EMAIL_ENTRY
            self._log("[3/6] Entering email...")
            email_input = await self.select("#email")
            await self.click(email_input)
            await self.type_text(email_input, email)
            await self.delay("short")
            self.state = ToppsState.EMAIL_ENTRY

            # State: CONTINUE_CLICKED
            continue_btn = await self.find("Continue")
            await self.click(continue_btn)
            await self.delay("page")
            self.state = ToppsState.CONTINUE_CLICKED

            # State: REGISTRATION_FORM
            self._log("[4/6] Filling registration form...")
            firstname_input = await self.select("#firstname")
            await self.click(firstname_input)
            await self.type_text(firstname_input, first_name)
            await self.delay("short")

            lastname_input = await self.select("#lastname")
            await self.click(lastname_input)
            await self.type_text(lastname_input, last_name)
            await self.delay("short")

            password_input = await self.select("#new-password")
            await self.click(password_input)
            await self.type_text(password_input, password, speed="slow")
            await self.delay("short")
            self.state = ToppsState.REGISTRATION_FORM

            # State: FORM_SUBMITTED
            self._log("[5/6] Submitting registration...")
            submit_btn = await self.find("Complete registration")
            await self.click(submit_btn)
            await self.delay("page")
            self.state = ToppsState.FORM_SUBMITTED

            # State: WAITING_EMAIL
            self._log("[6/6] Waiting for verification email...")
            self.state = ToppsState.WAITING_EMAIL
            verify_link = await email_client.wait_for_link(
                email,
                self.VERIFY_LINK_PATTERN,
                timeout=120,
                poll_interval=5,
                existing_links=existing_links,
                sender_filter=self.FANATICS_SENDER,
            )

            if not verify_link:
                return False, "Verification email not received"

            # State: VERIFICATION_LINK
            self._log("      Verifying email...")
            self._log(f"      Link: {verify_link[:80]}...")
            if not await self._transition_to(
                ToppsState.VERIFICATION_LINK,
                lambda: self.navigate(verify_link),
            ):
                return False, "Failed to navigate to verification link"

            await self.delay("page")  # Extra wait

            # State: COMPLETE
            self._log(f"      Final URL: {self.tab.target.url}")
            self.state = ToppsState.COMPLETE

            return True, "Account created and verified"

        except Exception as e:
            self.state = ToppsState.FAILED
            await self.take_screenshot(f"error_topps_{email.split('@')[0]}.png")
            return False, f"{str(e)} (state: {self.state.name})"
