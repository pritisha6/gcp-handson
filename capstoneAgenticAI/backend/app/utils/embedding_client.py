"""Local embedding generation via fastembed (ONNX-based, no torch dependency).

Runs entirely on-device (no external API call, no per-token cost, no
OPENAI_API_KEY) using a quantized ONNX model via the `fastembed` package,
replacing the OpenAI embeddings API this project used before. Chosen over
sentence-transformers/torch specifically because torch's packaged license
files nest deep enough to exceed Windows' default 260-character path limit
under this repo's path. Model weights are downloaded from the Hugging Face
Hub on first use and cached locally by fastembed itself; loading the model
is comparatively expensive, so it's cached per process here.
"""
from functools import lru_cache
from typing import List, Optional

from fastembed import TextEmbedding

from app.config import Settings, get_settings


@lru_cache(maxsize=4)
def _load_model(model_name: str) -> TextEmbedding:
    return TextEmbedding(model_name=model_name)


def get_embedding_model(settings: Optional[Settings] = None) -> TextEmbedding:
    """Return a process-wide cached embedding model for the configured EMBEDDING_MODEL."""
    settings = settings or get_settings()
    return _load_model(settings.EMBEDDING_MODEL)


def embed_texts(model: TextEmbedding, texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts, returning one vector per input, in the same order."""
    return [vector.tolist() for vector in model.embed(texts)]
