import asyncio
import logging
from typing import AsyncIterator
import aiohttp

logger = logging.getLogger(__name__)

class Scraper:
    def __init__(self, rate_limit: float = 0.5) -> None:
        self.delay = 1.0 / rate_limit
        self.semaphore = asyncio.Semaphore(1)
        self.headers = { 
            "User-Agent": "RunebearerEldenRingRAGCompanion/1.0 (Contact: localdev@domain.com)"
        }
    
    async def fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        async with self.semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, headers=self.headers, timeout=timeout) as response:
                    if response.status != 200:
                        raise aiohttp.ClientResponseError(
                            response.request_info, response.history,
                            status=response.status, message=f"Non-200 status code: {response.status}"
                        )
                    html = await response.text()
                    await asyncio.sleep(self.delay)  # Enforce spacing spacing post request
                    return html
            except Exception as e:
                logger.error(f"Error fetching URL {url}: {str(e)}")
                raise
    
    async def iter_pages(self, urls: list[str]) -> AsyncIterator[tuple[str, str]]:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                if not url.strip():
                    continue
                try:
                    html = await self.fetch(session, url.strip())
                    yield url, html
                except Exception:
                    # Isolate error per URL to keep pipeline running
                    continue