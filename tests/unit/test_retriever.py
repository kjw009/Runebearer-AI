from app.graph.state import RagChunk, Citation
from unittest.mock import MagicMock, AsyncMock, patch
from app.rag.retriever import Retriever

retriever = Retriever(pool=MagicMock())

query_vector = [1.0, 0.0, 0.0]
candidate_chunks = [
    {"content": "Malenia Phase 1 Waterfowl Dance dodge strategy",
    "source_url": "https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella",
    "page_title": "Malenia, Blade of Miquella - Elden Ring Wiki",
    "section": "Phase 1 Waterfowl Dance",
    "entity_type": "boss",
    "chunk_index": 0,
    "similarity_score": 0.9, 
    "embedding": [1.0, 0.0, 0.0]
    },
    {"content": "Malenia Phase 1 Waterfowl Dance dodge strategy 2", 
    "source_url": "https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella",
    "page_title": "Malenia, Blade of Miquella - Elden Ring Wiki",
    "section": "Phase 1 Waterfowl Dance",
    "entity_type": "boss",
    "chunk_index": 1,
    "similarity_score": 0.85, 
    "embedding": [0.98, 0.2, 0.0]
    },
    {"content": "Malenia Phase 2 Scarlet Aeonia strategy", 
    "source_url": "https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella",
    "page_title": "Malenia, Blade of Miquella - Elden Ring Wiki",
    "section": "Phase 2 Scarlet Aeonia",
    "entity_type": "boss",
    "chunk_index": 2,
    "similarity_score": 0.7, 
    "embedding": [0.0, 1.0, 0.0]
    },
    {"content": "Malenia Phase 2 Rotten Breath strategy", 
    "source_url": "https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella",
    "page_title": "Malenia, Blade of Miquella - Elden Ring Wiki",
    "section": "Phase 2 Rotten Breath",
    "entity_type": "boss",
    "chunk_index": 3,
    "similarity_score": 0.6, 
    "embedding": [0.3, 0.3, 0.9]
    },
    {"content": "Malenia Phase 2 Scarlet Aeonia strategy 2", 
    "source_url": "https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella",
    "page_title": "Malenia, Blade of Miquella - Elden Ring Wiki",
    "section": "Phase 2 Scarlet Aeonia",
    "entity_type": "boss",
    "chunk_index": 4,
    "similarity_score": 0.69, 
    "embedding": [0.5, 0.5, 0.7]
    },
    ]

async def test_mmr_selects_diverse_chunks(retriever=retriever, query_vector=query_vector, candidate_chunks=candidate_chunks, top_k=3, lambda_param=0.5):
    """
    Ensure MMR correctly penalizes redundant documents even if they have high similarity scores,
    favoring highly distinct documents down the similarity rank.
    """


    diverse_chunks = retriever._mmr(
        query_vector=query_vector, 
        candidate_chunks=candidate_chunks, 
        top_k=top_k, 
        lambda_param=lambda_param,
    )

    assert len(diverse_chunks) == 3
    # The first pick should be the most similar to the query
    assert diverse_chunks[0] == candidate_chunks[0]
    # The second pick should be Candidate 3 because Candidate 2 is severely penalized for redundancy
    assert diverse_chunks[1] == candidate_chunks[2]
    # The third pick should be Candidate 4 because Candidate 5 is penalized as its too similar to Candidate 3   
    assert diverse_chunks[2] == candidate_chunks[3]

@patch("app.rag.retriever.VectorRepository")
@patch("app.rag.retriever.Embedder")
async def test_retriever_returns_rag_chunks(
    mock_embedder,
    mock_repo,
    query="How do I beat Malenia's Waterfowl Dance?",
    entity_types=["boss"],
    top_k_cosine=20,
    top_k_mmr=10,
    mmr_lambda=0.5
    ):
    """
    Tests the Retriever's ability to return correctly formatted RAG chunks from a query
    based on candidate documents.
    """
    mock_embedder.return_value.embed = AsyncMock(return_value=[0.1] * 1536)
    mock_repo.return_value.similarity_search = AsyncMock(return_value=candidate_chunks)
    retriever = Retriever(pool=MagicMock())
    
    rag_chunks = await retriever.retrieve(
        query=query,
        entity_types=entity_types,
        top_k_cosine=top_k_cosine,
        top_k_mmr=top_k_mmr,
        mmr_lambda=mmr_lambda,
    )
    assert len(rag_chunks) <= top_k_mmr
    assert all(isinstance(chunk, RagChunk) for chunk in rag_chunks)
    assert all(hasattr(chunk, 'content') and hasattr(chunk, 'citation') and hasattr(chunk, 'similarity_score') for chunk in rag_chunks)
