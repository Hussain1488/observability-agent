from pydantic import BaseModel, Field
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import settings


class ModelConfig(BaseModel):
    provider: Literal["chatgpt", "GoogleGenAI"]
    model: str = Field(min_length=2, description="The version of the model to use.")


def get_model(config: ModelConfig | None = None):
    if config is None:
        config = ModelConfig(provider="chatgpt", model=settings.openai_model)

    match config.provider:
        case "chatgpt":
            return ChatOpenAI(
                model=config.model or settings.openai_model,
                api_key=settings.openai_api_key,
            )
        case "GoogleGenAI":
            return ChatGoogleGenerativeAI(
                model=config.model or settings.google_genai_model,
                api_key=settings.google_genai_api_key,
            )
        case _:
            raise ValueError(f"Unsupported provider: {config.provider}")

   
    raise ValueError(f"Unsupported provider: {config.provider}")