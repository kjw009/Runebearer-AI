from openai import AsyncOpenAI

class Embedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI()

    async def embed(self, text: str) -> list[float]:
        """Provides lightweight isolated lookup vector for queries at execution runtime"""
        response = await self._client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding