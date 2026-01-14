import asyncio
import os
import random
import secrets
import string

from dotenv import load_dotenv
from faker import Faker

from autofw import BrowserConfig, GmailConfig
from autofw.email import GmailClient
from autofw.examples.topps import ToppsAccountGenerator


def generate_password(length: int = 16) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%" for c in password)
        ):
            return password


def generate_account_data(catchall_domain: str) -> dict:
    """Generate random account data."""
    fake = Faker()
    first_name = fake.first_name()
    last_name = fake.last_name()
    suffix = random.randint(1000, 9999)
    username = f"{first_name}{last_name}{suffix}"

    return {
        "email": f"{username}@{catchall_domain}",
        "first_name": first_name,
        "last_name": last_name,
        "password": generate_password(),
    }


async def main():
    load_dotenv()

    catchall_domain = os.getenv("CATCHALL_DOMAIN")
    gmail_email = os.getenv("GMAIL_EMAIL")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all([catchall_domain, gmail_email, gmail_app_password]):
        print("Missing required environment variables:")
        print("  CATCHALL_DOMAIN - Your catchall email domain")
        print("  GMAIL_EMAIL - Your Gmail address")
        print("  GMAIL_APP_PASSWORD - Your Gmail app password")
        return

    # Generate account data
    account = generate_account_data(catchall_domain)
    print(f"Creating account: {account['email']}")
    print(f"  Name: {account['first_name']} {account['last_name']}")

    # Setup email client
    email_client = GmailClient(
        GmailConfig(
            email=gmail_email,
            app_password=gmail_app_password,
        )
    )

    # Setup browser
    config = BrowserConfig(
        headless=False,
        speed=1.5,
        debug_cursor=True,
    )
    generator = ToppsAccountGenerator(config=config)

    try:
        await generator.start()
        success, message = await generator.create_account(
            email=account["email"],
            first_name=account["first_name"],
            last_name=account["last_name"],
            password=account["password"],
            email_client=email_client,
        )

        if success:
            print("\nSuccess! Account created:")
            print(f"  Email: {account['email']}")
            print(f"  Password: {account['password']}")
        else:
            print(f"\nFailed: {message}")

    finally:
        await generator.stop()


if __name__ == "__main__":
    asyncio.run(main())
