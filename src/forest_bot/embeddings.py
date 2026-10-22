"""Local multilingual sentence embeddings (Groq has no embeddings API).

`python -m forest_bot.embeddings` downloads the model; the Dockerfile runs it at build time.
"""

import asyncio
from functools import cached_property

import numpy as np
from fastembed import TextEmbedding

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSIONS = 384


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name

    @cached_property
    def _model(self) -> TextEmbedding:
        return TextEmbedding(self._model_name)

    def embed_sync(self, texts: list[str]) -> list[np.ndarray]:
        return list(self._model.embed(texts))

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        # The model is CPU-bound; keep the event loop free for Telegram updates
        return await asyncio.to_thread(self.embed_sync, texts)


if __name__ == "__main__":
    vector = Embedder().embed_sync(["Коли йти по гриби?"])[0]
    assert vector.shape == (DIMENSIONS,), vector.shape
    print(f"{MODEL_NAME} is ready, {DIMENSIONS} dimensions")
