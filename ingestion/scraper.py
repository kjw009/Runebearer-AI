import asyncio
import logging
from typing import AsyncIterator
import aiohttp

# __name__ gives this logger the module path (e.g. "ingestion.scraper"),
# which makes it easy to filter log output by module in production.
logger = logging.getLogger(__name__)


class Scraper:
    def __init__(self, rate_limit: float = 0.5) -> None:
        # Convert requests-per-second to seconds-per-request.
        # rate_limit=0.5 means 0.5 req/s → wait 2 seconds between requests.
        self.delay = 1.0 / rate_limit

        # Semaphore(1) acts as a mutex — only one coroutine can hold it at a
        # time. This enforces that only one HTTP request is in flight at once,
        # which combined with self.delay gives us reliable rate limiting.
        # Using just asyncio.sleep() without a semaphore wouldn't work: two
        # coroutines could both exit their sleep at the same time and fire
        # concurrent requests, blowing through the rate limit.
        self.semaphore = asyncio.Semaphore(1)

        # Wikis and public sites often block requests with no User-Agent, or
        # treat them as bots. A descriptive User-Agent is polite scraping
        # practice and reduces the chance of getting blocked.
        self.headers = {
            "User-Agent": "RunebearerEldenRingRAGCompanion/1.0 (Contact: localdev@domain.com)"
        }

    async def fetch(self, session: aiohttp.ClientSession, url: str) -> str:
        # The semaphore is acquired here, wrapping both the HTTP request AND
        # the sleep. This is intentional — if the sleep were outside the
        # semaphore, another coroutine could acquire it while we're sleeping
        # and immediately fire a second request, defeating the rate limit.
        async with self.semaphore:
            try:
                # total=10 means the entire request (connect + read) must
                # complete within 10 seconds, else aiohttp raises TimeoutError.
                timeout = aiohttp.ClientTimeout(total=10)

                # session.get() returns a context manager. We use `async with`
                # so the response is properly closed even if we raise an exception.
                async with session.get(url, headers=self.headers, timeout=timeout) as response:
                    if response.status != 200:
                        raise aiohttp.ClientResponseError(
                            response.request_info, response.history,
                            status=response.status,
                            message=f"Non-200 status code: {response.status}",
                        )
                    html = await response.text()

                    # Sleep after reading the response body but still inside the
                    # semaphore, so the next fetch() call cannot start until the
                    # full delay has elapsed.
                    await asyncio.sleep(self.delay)
                    return html

            except Exception as e:
                # Log with %s placeholders rather than an f-string. Logging
                # defers string formatting until the message is actually emitted,
                # so if this log level is disabled, no formatting cost is paid.
                logger.error("Error fetching URL %s: %s", url, e)
                # Re-raise so iter_pages() can catch it and decide whether to
                # skip this URL or abort.
                raise

    async def iter_pages(self, urls: list[str]) -> AsyncIterator[tuple[str, str]]:
        # One ClientSession is created for the entire batch of URLs and reused
        # for every fetch() call. Creating a new session per request would
        # open and close a TCP connection each time — expensive and unnecessary.
        # The `async with` block closes the session and releases all connections
        # when iteration is complete, even if an exception is raised.
        async with aiohttp.ClientSession() as session:
            for url in urls:
                # Skip blank lines that may appear in the URL source files.
                if not url.strip():
                    continue
                try:
                    html = await self.fetch(session, url.strip())
                    # yield makes this an async generator — the caller receives
                    # (url, html) pairs one at a time without waiting for all
                    # URLs to be fetched first.
                    yield url, html
                except Exception:
                    # logger.exception automatically appends the full traceback
                    # to the log message, which is more useful than logger.error
                    # when debugging a failed scrape.
                    # We catch and continue rather than re-raising so one bad
                    # URL doesn't abort the entire ingestion pipeline.
                    logger.exception("Skipping %s", url.strip())
                    continue