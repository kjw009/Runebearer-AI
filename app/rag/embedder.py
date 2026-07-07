from openai import APIConnectionError, AsyncOpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import settings


class Embedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key
        )

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(4),
    )
    async def embed(self, text: str) -> list[float]:
        """Query-time embedding — single string in, single vector out.

        Kept separate from IngestEmbedder which handles batch ingestion.
        """
        response = await self._client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding