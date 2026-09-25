from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # so HF_HUB_OFFLINE=1 in .env takes effect before the model loads

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384


@lru_cache(maxsize=1)
def _model():
    # Imported lazily: loading torch is slow, and the first run downloads ~90 MB.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def embed(texts):
    """Return normalized embeddings as plain Python lists."""
    return _model().encode(texts, normalize_embeddings=True).tolist()


def to_pgvector(vec):
    """Format a vector as a pgvector literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"