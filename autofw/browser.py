import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

import nodriver as uc
import nodriver.cdp.input_ as cdp_input
import nodriver.cdp.network as cdp_network

from autofw.delays import DelayProfile, random_delay
from autofw.mouse import HumanMouse, MouseConfig
from autofw.retry import RetryConfig, retry
from autofw.typing import TypingConfig, human_type

CURSOR_INJECT_JS = """(function(){if(document.getElementById('__debug_cursor__'))return;const c=document.createElement('div');c.id='__debug_cursor__';c.style.cssText='position:fixed;width:12px;height:12px;background:rgba(255,50,50,0.8);border:2px solid white;border-radius:50%;pointer-events:none;z-index:999999;transform:translate(-50%,-50%);box-shadow:0 0 4px rgba(0,0,0,0.5);transition:none';document.body.appendChild(c)})();"""
CURSOR_MOVE_JS = "(function(x,y){const c=document.getElementById('__debug_cursor__');if(c){c.style.left=x+'px';c.style.top=y+'px'}})(%s,%s);"

DEFAULT_BROWSER_ARGS = [
    "--disable-remote-fonts",
    "--disable-background-networking",
    "--disable-default-apps",
    "--no-pings",
]

DEFAULT_BLOCKED_PATTERNS = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.svg",
    "*.ico",
    "*.mp4",
    "*.webm",
    "*.mp3",
    "*.wav",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*google-analytics.com*",
    "*googletagmanager.com*",
    "*facebook.com/tr*",
    "*doubleclick.net*",
    "*hotjar.com*",
]


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = False
    speed: float = 1.0
    proxy: str | None = None
    debug_cursor: bool = False
    window_position: tuple[int, int] = (50, 50)
    window_size: tuple[int, int] = (1200, 800)
    browser_args: list[str] = field(default_factory=list)


class Browser:
    def __init__(
        self,
        config: BrowserConfig | None = None,
        retry_config: RetryConfig | None = None,
        mouse_config: MouseConfig | None = None,
        delay_profile: DelayProfile | None = None,
    ):
        self.config = config or BrowserConfig()
        self.retry_config = retry_config or RetryConfig()
        self.delay_profile = delay_profile or DelayProfile(speed_multiplier=self.config.speed)

        mouse_cfg = mouse_config or MouseConfig()
        adjusted_speed = mouse_cfg.speed_factor * (1 / self.config.speed)
        self.mouse = HumanMouse(
            MouseConfig(
                speed_factor=adjusted_speed,
                zigzag_probability=mouse_cfg.zigzag_probability,
                min_nodes=mouse_cfg.min_nodes,
                max_nodes=mouse_cfg.max_nodes,
                variance_factor=mouse_cfg.variance_factor,
                max_variance=mouse_cfg.max_variance,
                points_per_path=mouse_cfg.points_per_path,
            )
        )

        self.cursor_x: float = 0
        self.cursor_y: float = 0
        self.browser: uc.Browser | None = None
        self.tab: uc.Tab | None = None

    async def start(self) -> None:
        x, y = self.config.window_position
        w, h = self.config.window_size
        browser_args = [
            f"--window-position={x},{y}",
            f"--window-size={w},{h}",
            *DEFAULT_BROWSER_ARGS,
            *self.config.browser_args,
        ]
        self.browser = await uc.start(headless=self.config.headless, browser_args=browser_args)
        self.cursor_x, self.cursor_y = random.uniform(100, 400), random.uniform(100, 300)

    async def stop(self) -> None:
        if not self.browser:
            return
        try:
            self.browser.stop()
        except Exception:
            pass
        await asyncio.sleep(1)
        self.browser, self.tab = None, None

    async def navigate(self, url: str, use_proxy: bool = False) -> uc.Tab:
        """Navigate to a URL, optionally using proxy."""
        if use_proxy and self.config.proxy:
            if self.browser.tabs:
                await self.browser.tabs[0].close()
            self.tab = await self.browser.create_context(url=url, proxy_server=self.config.proxy)
        else:
            self.tab = await self.browser.get(url)
        await self._inject_debug_cursor()
        return self.tab

    async def select(self, selector: str, timeout: int = 10) -> Any:
        """Select an element by CSS selector with retry."""

        async def select_with_timeout():
            return await asyncio.wait_for(self.tab.select(selector), timeout=timeout)

        return await retry(select_with_timeout, self.retry_config, f"select '{selector}'")

    async def find(self, text: str, best_match: bool = True, timeout: int = 10) -> Any:
        """Find an element by text content with retry."""

        async def find_with_timeout():
            return await asyncio.wait_for(self.tab.find(text, best_match=best_match), timeout=timeout)

        return await retry(find_with_timeout, self.retry_config, f"find '{text}'")

    async def click(self, element) -> None:
        """Click an element with human-like mouse movement."""
        await self._human_move_to(element)
        await retry(lambda: element.click(), self.retry_config, "click")

    async def apply(self, element, js: str) -> Any:
        """Execute JavaScript on an element with retry."""
        return await retry(lambda: element.apply(js), self.retry_config, "apply JS")

    async def type_text(self, element, text: str, speed: str = "normal") -> None:
        """Type text with human-like delays."""
        await human_type(element, text, TypingConfig(speed=speed), self.config.speed)

    async def delay(self, mode: str = "action") -> None:
        """Wait for a random duration based on delay mode."""
        await random_delay(mode, self.delay_profile)

    async def take_screenshot(self, filename: str) -> None:
        if self.tab:
            try:
                await self.tab.save_screenshot(filename)
            except Exception:
                pass

    async def block_resources(self, patterns: list[str] | None = None) -> None:
        """Block resource loading via CDP to save bandwidth."""
        if not self.tab:
            return
        try:
            await self.tab.send(cdp_network.enable())
            await self.tab.send(cdp_network.set_blocked_ur_ls(urls=patterns or DEFAULT_BLOCKED_PATTERNS))
        except Exception:
            pass

    async def _inject_debug_cursor(self) -> None:
        if not (self.config.debug_cursor and self.tab):
            return
        try:
            await self.tab.evaluate(CURSOR_INJECT_JS)
            await self.tab.evaluate(CURSOR_MOVE_JS % (self.cursor_x, self.cursor_y))
        except Exception:
            pass

    async def _move_mouse(self, x: float, y: float) -> None:
        await self.tab.send(cdp_input.dispatch_mouse_event(type_="mouseMoved", x=x, y=y))
        if self.config.debug_cursor:
            try:
                await self.tab.evaluate(CURSOR_MOVE_JS % (x, y))
            except Exception:
                pass

    async def _get_element_center(self, element) -> tuple[float, float]:
        box = await element.get_position()
        return (
            box.x + box.width / 2 + random.uniform(-box.width * 0.15, box.width * 0.15),
            box.y + box.height / 2 + random.uniform(-box.height * 0.15, box.height * 0.15),
        )

    async def _human_move_to(self, element) -> None:
        target_x, target_y = await self._get_element_center(element)
        path = self.mouse.generate_path(self.cursor_x, self.cursor_y, target_x, target_y)
        delays = self.mouse.calculate_delays(path)
        for (x, y), delay in zip(path, delays):
            await self._move_mouse(x, y)
            await asyncio.sleep(delay / 1000)
        self.cursor_x, self.cursor_y = target_x, target_y
