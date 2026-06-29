import numpy as np
import asyncpg
from app.db.repositories.vectors import VectorRepository
from app.rag.embedder import Embedder
from app.graph.state import RagChunk, Citation

class Retriever:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._repo = VectorRepository(pool)
        self._embedder = Embedder()

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Calculates the cosine similarity between two vectors"""
        arr_a, arr_b = np.array(vec_a), np.array(vec_b)
        norm_a = np.linalg.norm(arr_a)
        norm_b = np.linalg.norm(arr_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0  # Avoid division by zero; treat zero vectors as having no similarity
        return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))
        
    def _mmr(self, query_vector: list[float], candidate_chunks: list[dict], lambda_param: float = 0.5, top_k: int = 5) -> list[dict]:
        """Applies Maximal Marginal Relevance (MMR) to select diverse and relevant chunks"""
        if not candidate_chunks:
            return []
        
        selected_chunks : list[dict] = []
        # Parse standard string array configuration back to pure numerical floats if required
        for candidate in candidate_chunks:
            if isinstance(candidate['embedding'], str):
                candidate['embedding'] = [float(x) for x in candidate['embedding'].strip('[]').split(',')]

        while len(selected_chunks) < min(top_k, len(candidate_chunks)):
            best_score = -float('inf')
            best_candidate = None

            for candidate in candidate_chunks:
                if candidate in selected_chunks:
                    continue  # Skip already selected candidates

                # Equation component 1: Equation alignment similarity with target original raw search intent vector
                similarity_with_query = candidate['similarity_score']

                # Equation component 2: Core calculation penalization factor vs items already chosen
                similarity_with_selected = 0.0
                if selected_chunks:
                    similarity_with_selected = max(
                        self._cosine_similarity(candidate['embedding'], selected['embedding']) 
                        for selected in selected_chunks
                    )                

                # MMR score calculation
                mmr_score = (lambda_param * similarity_with_query) - ((1 - lambda_param ) * similarity_with_selected)

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_candidate = candidate

            if best_candidate:
                selected_chunks.append(best_candidate)
            else:
                break  # No more candidates to select
        
        return selected_chunks  
    
    async def retrieve(
            self, 
            query: str, 
            entity_types: list[str], 
            top_k_cosine: int = 20, 
            top_k_mmr: int = 10, 
            mmr_lambda: float = 0.5
        ) -> list[RagChunk]:
        """Retrieves relevant chunks based on the query, applying cosine similarity and MMR for diversity"""
        # Step 1: Generate embedding for the query
        query_vector = await self._embedder.embed(query)
        candidate_chunks = await self._repo.similarity_search(query_vector, entity_types, top_k_cosine)

        diverse_chunks = self._mmr(query_vector, candidate_chunks, lambda_param=mmr_lambda, top_k=top_k_mmr)

        # Convert the selected chunks into RagChunk dataclass instances
        return [
            RagChunk(
                content=chunk['content'],
                citation=Citation(
                    source_url=chunk['source_url'],
                    page_title=chunk['page_title'],
                    section=chunk['section'],
                    chunk_index=chunk['chunk_index'],
                ),
                similarity_score=chunk['similarity_score']
            )
            for chunk in diverse_chunks
        ]