from sentence_transformers import CrossEncoder
from app.rag.retriever import RagChunk

class Reranker:
    def __init__(self) -> None:
        self._cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

    def rerank(self, query: str, chunks: list[RagChunk], top_k: int = 5) -> list[RagChunk]:
        if not chunks:
            return []
        
        # Prepare the input pairs for the cross-encoder
        input_pairs = [(query, chunk.content) for chunk in chunks]

        # Compute relevance scores using the cross-encoder
        scores = self._cross_encoder.predict(input_pairs)

        # Combine chunks with their corresponding scores    
        scored_chunks = sorted(zip(chunks, scores), key=lambda mapping: mapping[1], reverse=True)

        # Return the top-k reranked chunks
        return [chunk for chunk, score in scored_chunks[:top_k]]