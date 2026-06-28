from openai import AsyncOpenAI
from app.config import settings

class Embedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key
        )

    async def embed(self, text: str) -> list[float]:
        """Query-time embedding — single string in, single vector out. Kept separate from IngestEmbedder which handles batch ingestion."""
        response = await self._client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding