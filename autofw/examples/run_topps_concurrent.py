import asyncio
import csv
import os
import random
import secrets
import string
from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv
from faker import Faker

from autofw import BrowserConfig, GmailConfig
from autofw.email import GmailClient
from autofw.examples.topps import ToppsAccountGenerator


@dataclass
class AccountResult:
    email: str
    password: str
    success: bool
    message: str


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


def save_results_to_csv(results: list[AccountResult], filename: str = "accounts.csv"):
    """Append successful accounts to CSV file."""
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "email", "password", "status"])
        for result in results:
            if result.success:
                writer.writerow(
                    [
                        datetime.now().isoformat(),
                        result.email,
                        result.password,
                        "success",
                    ]
                )


class TileManager:
    """Manages tiled window positions for concurrent browsers."""

    def __init__(
        self,
        max_tiles: int = 12,
        columns: int = 4,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ):
        self.max_tiles = max_tiles
        # Adjust columns if fewer tiles than columns
        self.columns = min(columns, max_tiles)
        self.rows = max(1, (max_tiles + self.columns - 1) // self.columns)  # Ceiling division
        self.window_width = screen_width // self.columns
        self.window_height = screen_height // self.rows
        self._available = list(range(max_tiles))
        self._lock = asyncio.Lock()

    async def acquire(self) -> int:
        """Get an available tile slot."""
        async with self._lock:
            if self._available:
                return self._available.pop(0)
            return 0  # Fallback to first position

    async def release(self, slot: int):
        """Return a tile slot to the pool."""
        async with self._lock:
            if slot not in self._available and slot < self.max_tiles:
                self._available.append(slot)
                self._available.sort()

    def get_position(self, slot: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """Get window position and size for a tile slot."""
        col = slot % self.columns
        row = (slot // self.columns) % self.rows
        x = col * self.window_width
        y = row * self.window_height
        return (x, y), (self.window_width, self.window_height)


async def create_single_account(
    instance_id: int,
    account_data: dict,
    email_client: GmailClient,
    semaphore: asyncio.Semaphore,
    tile_manager: TileManager,
) -> AccountResult:
    """Create a single account with semaphore-controlled concurrency."""
    async with semaphore:
        # Acquire a tile slot for window positioning
        tile_slot = await tile_manager.acquire()
        position, size = tile_manager.get_position(tile_slot)

        config = BrowserConfig(
            headless=False,
            speed=1.5,
            debug_cursor=True,
            window_position=position,
            window_size=size,
        )
        generator = ToppsAccountGenerator(config=config, instance_id=instance_id)
        try:
            await generator.start()
            success, message = await generator.create_account(
                email=account_data["email"],
                first_name=account_data["first_name"],
                last_name=account_data["last_name"],
                password=account_data["password"],
                email_client=email_client,
            )
            return AccountResult(
                email=account_data["email"],
                password=account_data["password"],
                success=success,
                message=message,
            )
        except Exception as e:
            return AccountResult(
                email=account_data["email"],
                password=account_data["password"],
                success=False,
                message=str(e),
            )
        finally:
            await generator.stop()
            await tile_manager.release(tile_slot)


async def main():
    load_dotenv()

    # Required config
    catchall_domain = os.getenv("CATCHALL_DOMAIN")
    gmail_email = os.getenv("GMAIL_EMAIL")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all([catchall_domain, gmail_email, gmail_app_password]):
        print("Missing required environment variables:")
        print("  CATCHALL_DOMAIN - Your catchall email domain")
        print("  GMAIL_EMAIL - Your Gmail address")
        print("  GMAIL_APP_PASSWORD - Your Gmail app password")
        return

    # Optional config with defaults
    num_accounts = int(os.getenv("NUM_ACCOUNTS", "3"))
    max_concurrent = int(os.getenv("MAX_CONCURRENT", "2"))

    print("Configuration:")
    print(f"  Accounts to create: {num_accounts}")
    print(f"  Max concurrent: {max_concurrent}")
    print()

    # Setup shared email client
    email_client = GmailClient(
        GmailConfig(
            email=gmail_email,
            app_password=gmail_app_password,
        )
    )

    # Create semaphore for browser concurrency and tile manager for window positions
    semaphore = asyncio.Semaphore(max_concurrent)
    tile_manager = TileManager(max_tiles=max_concurrent)

    # Generate account data for all accounts
    accounts = [generate_account_data(catchall_domain) for _ in range(num_accounts)]

    print("Accounts to create:")
    for i, acc in enumerate(accounts):
        print(f"  [{i}] {acc['email']}")
    print()

    # Run all account creations concurrently with tiled windows
    tasks = [create_single_account(i, acc, email_client, semaphore, tile_manager) for i, acc in enumerate(accounts)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter valid results
    valid_results = [r for r in results if isinstance(r, AccountResult)]

    # Save successful accounts to CSV
    save_results_to_csv(valid_results)

    # Print summary
    successful = sum(1 for r in valid_results if r.success)
    failed = len(valid_results) - successful
    errors = len(results) - len(valid_results)

    print()
    print("=" * 50)
    print(f"RESULTS: {successful} success, {failed} failed, {errors} errors")
    print("=" * 50)
    for result in results:
        if isinstance(result, Exception):
            print(f"  ERROR: {result}")
        elif result.success:
            print(f"  OK: {result.email}")
        else:
            print(f"  FAIL: {result.email} - {result.message}")

    if successful > 0:
        print("\nAccounts saved to accounts.csv")


if __name__ == "__main__":
    asyncio.run(main())
