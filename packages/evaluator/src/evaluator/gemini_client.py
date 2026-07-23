import json
import os

from google import genai
from google.genai import types

from .schemas import PromptMetadata


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str = "gemini-3.1-flash-lite"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY is required. Set it as an environment variable "
                "or pass it to GeminiClient(api_key=...)."
            )
        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def evaluate(self, prompt_meta: PromptMetadata) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt_meta.prompt,
            config=types.GenerateContentConfig(
                temperature=prompt_meta.temperature,
                response_mime_type="application/json",
            ),
        )
        return response.text
