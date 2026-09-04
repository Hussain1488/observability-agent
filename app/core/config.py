from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = "gpt-4o-mini"

    google_genai_api_key: str = os.getenv("GOOGLE_GENAI_API_KEY", "")
    google_genai_model: str = "gemini-3.5-flash-lite"

settings = Settings()

