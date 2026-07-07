import logging

from openai import APIConnectionError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import settings


class QueryExpansion(BaseModel):
    variants: list[str] = Field(
        ..., 
        description="Exactly 3 search-optimized query reformulations containing enriched domain vocabulary."
    )

class QueryRewriter:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key
        )

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
        wait=wait_random_exponential(min=1, max=20),
        stop=stop_after_attempt(4),
    )
    async def _call_openai(self, system_instructions: str, user_content: str):
        """Retried inner call — only rate-limit / connection errors are retried."""
        return await self._client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_content}
            ],
            response_format=QueryExpansion,
            temperature=0.1,
            max_tokens=300
        )

    async def rewrite(self, query: str, calling_agent: str) -> list[str]:
        """Rewrites the query to be more specific and relevant to the calling agent"""
        system_instructions = (
            "You are an expert Elden Ring systems analyst backend RAG component.\n"
            "Your objective is to consume a raw player query and convert it into exactly 3 alternate "
            "search-optimized keyword variants that enrich vector search operations.\n"
            "Expand short terms or video game abbreviations to structural keywords (e.g., 'bleed' -> 'hemorrhage loss buildup', "
            "'malenia tips' -> 'waterfowl dance physical poise mitigation').\n"
            "Tailor variations specifically for the component domain perspective requested."
        )
        user_content = f"Calling Agent Domain Context: {calling_agent}\nRaw Query Target: {query}"
        
        try:
            response = await self._call_openai(system_instructions, user_content)
            # Extract the parsed Pydantic object directly from the response wrapper
            parsed_response: QueryExpansion | None = response.choices[0].message.parsed
            if parsed_response and len(parsed_response.variants) >= 3:
                return parsed_response.variants[:3]  # guard: model occasionally returns 4+ despite the prompt instruction
        except Exception as e:
            logging.error("Failed to rewrite query: %s", e)
        
        # Safe resilient fallback strategy returning the original query if the API fails
        return [query]