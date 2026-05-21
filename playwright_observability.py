"""
Playwright browser automation for Noble Team observability.
Provides screenshot capture, element inspection, and interaction recording.
"""
import asyncio
from playwright.async_api import async_playwright, Page, Browser
from datetime import datetime
from typing import Optional, Dict, Any
import json
import os

SCREENSHOT_DIR = "/workspace/noble-hq/public/screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

class NobleObservability:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None

    async def start(self, headless: bool = True):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.page = await self.browser.new_page(viewport={"width": 1920, "height": 1080})
        return self

    async def stop(self):
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def screenshot_dashboard(self, url: str = "http://localhost:8500") -> str:
        """Capture full dashboard screenshot."""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"dashboard_{ts}.png"
        path = os.path.join(SCREENSHOT_DIR, filename)
        
        await self.page.goto(url, wait_until="networkidle")
        await self.page.screenshot(path=path, full_page=True)
        
        return path

    async def screenshot_element(self, selector: str, url: str = "http://localhost:8500") -> str:
        """Capture specific element screenshot."""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"element_{selector.replace('#', '').replace('.', '')}_{ts}.png"
        path = os.path.join(SCREENSHOT_DIR, filename)
        
        await self.page.goto(url, wait_until="networkidle")
        element = await self.page.wait_for_selector(selector)
        await element.screenshot(path=path)
        
        return path

    async def inspect_page(self, url: str = "http://localhost:8500") -> Dict[str, Any]:
        """Inspect page structure and key metrics."""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        await self.page.goto(url, wait_until="networkidle")
        
        metrics = await self.page.evaluate("""() => ({
            title: document.title,
            url: window.location.href,
            viewport: { width: window.innerWidth, height: window.innerHeight },
            elements: {
                buttons: document.querySelectorAll('button').length,
                links: document.querySelectorAll('a').length,
                inputs: document.querySelectorAll('input').length,
                charts: document.querySelectorAll('canvas, svg').length,
            },
            errors: (window.__errors || []).length,
            loadTime: performance.timing.loadEventEnd - performance.timing.navigationStart,
        })""")
        
        return metrics

    async def record_interaction(self, url: str = "http://localhost:8500", actions: list = None) -> str:
        """Record a sequence of interactions and capture result."""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"interaction_{ts}.png"
        path = os.path.join(SCREENSHOT_DIR, filename)
        
        await self.page.goto(url, wait_until="networkidle")
        
        # Perform actions
        for action in (actions or []):
            action_type = action.get("type")
            selector = action.get("selector")
            value = action.get("value")
            
            if action_type == "click":
                await self.page.click(selector)
            elif action_type == "fill":
                await self.page.fill(selector, value)
            elif action_type == "wait":
                await asyncio.sleep(value or 1)
            elif action_type == "screenshot":
                await self.page.screenshot(path=path, full_page=True)
                return path
        
        await self.page.screenshot(path=path, full_page=True)
        return path

    async def capture_operator_view(self, operator_id: str, url: str = "http://localhost:8500") -> str:
        """Navigate to operators tab and capture specific operator profile."""
        if not self.page:
            raise RuntimeError("Browser not started")
        
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"operator_{operator_id}_{ts}.png"
        path = os.path.join(SCREENSHOT_DIR, filename)
        
        await self.page.goto(url, wait_until="networkidle")
        
        # Click operators tab
        await self.page.click("text=OPERATORS")
        await asyncio.sleep(0.5)
        
        # Click specific operator card
        await self.page.click(f"[data-operator-id='{operator_id}']")
        await asyncio.sleep(0.5)
        
        await self.page.screenshot(path=path, full_page=True)
        return path

async def main():
    obs = await NobleObservability().start()
    try:
        # Example: capture dashboard
        path = await obs.screenshot_dashboard("http://localhost:8500")
        print(f"Screenshot saved: {path}")
        
        # Example: inspect metrics
        metrics = await obs.inspect_page("http://localhost:8500")
        print(json.dumps(metrics, indent=2))
    finally:
        await obs.stop()

if __name__ == "__main__":
    asyncio.run(main())
