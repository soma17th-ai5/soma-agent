from typing import AsyncGenerator, List

from openai import AsyncOpenAI, APIConnectionError
from retry import retry

from soma_app.core.logger import logger
from soma_app.core.errors.error import OpenAIException
from soma_app.core.config import config
from soma_app.models.schemas import EmbeddingResult

class OpenAIClient:
    def __init__(self, base_url: str):
        self.client = AsyncOpenAI(
            api_key=config.API_KEY,
            base_url=base_url
        )

    @retry(tries=5, delay=1, backoff=2, exceptions=APIConnectionError)
    async def embeddings(self, messages: List[str], model: str = "solar-embedding-1-large-query", **kwargs) -> List[EmbeddingResult]:
        logger.info("Generating embeddings")
        try:
            response = await self.client.embeddings.create(
                model=model,
                input=messages,
                **kwargs,
            )

            return [EmbeddingResult(**data.model_dump()) for data in response.data]
        except Exception as e:
            logger.error(e)
            raise OpenAIException(f"Embedding failed: {e}")

    @retry(tries=5, delay=1, backoff=2, exceptions=APIConnectionError)
    async def generate(self, messages: List[dict], model: str = "solar-1-mini-chat", **kwargs) -> str:
        logger.info(f"Generating completion for message: {messages}, model: {model}")
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                **kwargs,
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM Completion failed: {e}")
            raise OpenAIException("AI 서비스 요청 중 내부 오류가 발생했습니다.")

    @retry(tries=5, delay=1, backoff=2, exceptions=APIConnectionError)
    async def stream_generate(self, messages: List[dict], model: str = "solar-1-mini-chat", **kwargs) -> AsyncGenerator[str, None]:
        logger.info(f"Generating stream completion for messages: {messages}, model: {model}")
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                **kwargs,
            )

            async for chunk in response:
                current_content = chunk.choices[0].delta.content
                if current_content:
                    yield current_content
                else:
                    continue
        except Exception as e:
            logger.error(f"LLM Stream Completion failed: {e}")
            raise OpenAIException("AI 서비스 요청 중 내부 오류가 발생했습니다.")
