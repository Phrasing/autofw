import re

from autofw.browser import Browser
from autofw.email import GmailClient


class ToppsAccountGenerator(Browser):
    TOPPS_URL = "https://www.topps.com/"
    FANATICS_SENDER = "no-reply@t.one.fan"
    VERIFY_LINK_PATTERN = re.compile(r"https://[^\s\"'<>]+verify-email[^\s\"'<>]+token=[^\s\"'<>]+")

    def __init__(self, config=None, instance_id: int = 0):
        super().__init__(config)
        self.instance_id = instance_id

    def _log(self, msg: str):
        """Print with instance ID prefix for concurrent logging."""
        print(f"[{self.instance_id}] {msg}")

    async def create_account(
        self,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        email_client: GmailClient,
    ) -> tuple[bool, str]:
        """Create a Topps account and verify via email link."""
        try:
            # Get existing verification links before registration
            existing_links = await email_client.get_existing_links(
                email, self.VERIFY_LINK_PATTERN, self.FANATICS_SENDER
            )

            # Navigate to homepage first, then to login
            self._log("[1/5] Navigating to Topps...")
            await self.navigate("https://www.topps.com/")
            await self.delay("page")

            # Handle Cloudflare verification if present
            await self.tab.verify_cf()

            # Now navigate to login page
            self._log("      Going to login page...")
            await self.navigate("https://www.topps.com/customer/account/login")
            await self.delay("page")
            await self.delay("page")  # Extra wait for redirects

            # Handle Cloudflare verification if present on login page
            await self.tab.verify_cf()

            self._log(f"      Current URL: {self.tab.target.url}")

            # Enter email
            self._log("[2/5] Entering email...")
            email_input = await self.select("#email")
            await self.click(email_input)
            await self.type_text(email_input, email)
            await self.delay("short")

            # Click continue
            continue_btn = await self.find("Continue")
            await self.click(continue_btn)
            await self.delay("page")

            # Fill registration form
            self._log("[3/5] Filling registration form...")
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

            # Submit registration
            self._log("[4/5] Submitting registration...")
            submit_btn = await self.find("Complete registration")
            await self.click(submit_btn)
            await self.delay("page")

            # Wait for verification email
            self._log("[5/5] Waiting for verification email...")
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

            # Navigate to verification link
            self._log("      Verifying email...")
            self._log(f"      Link: {verify_link[:80]}...")
            await self.navigate(verify_link)
            await self.delay("page")
            await self.delay("page")  # Extra wait

            # Debug: print final URL
            self._log(f"      Final URL: {self.tab.target.url}")

            return True, "Account created and verified"

        except Exception as e:
            await self.take_screenshot(f"error_topps_{email.split('@')[0]}.png")
            return False, str(e)
