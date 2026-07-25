import json
import os
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError

from .schemas import PromptMetadata

# Candidate models across regions in order of fallback
MODELS_TO_TRY = [
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
]


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str = "gemini-3.1-flash-lite"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY is required. Set it as an environment variable "
                "or pass it to GeminiClient(api_key=...)."
            )
        self.client = genai.Client(api_key=self.api_key)
        self.model = os.getenv("GEMINI_MODEL", model)

    def evaluate(self, prompt_meta: PromptMetadata) -> str:
        models = [self.model] + [m for m in MODELS_TO_TRY if m != self.model]
        last_err = None

        for model_name in models:
            for attempt in range(4):
                try:
                    import sys
                    sys.stderr.write(f"[evaluator/gemini_client] Calling Gemini API (model={model_name}, attempt={attempt+1})...\n")
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt_meta.prompt,
                        config=types.GenerateContentConfig(
                            temperature=prompt_meta.temperature,
                            response_mime_type="application/json",
                        ),
                    )
                    if response and response.text:
                        sys.stderr.write(f"[evaluator/gemini_client] ✅ Gemini API success with model={model_name}\n")
                        return response.text
                except (ServerError, APIError, Exception) as e:
                    last_err = e
                    err_msg = str(e)
                    # If model is unavailable, rate-limited, or 503 high-demand, retry or fallback
                    if (
                        "503" in err_msg
                        or "429" in err_msg
                        or "UNAVAILABLE" in err_msg
                        or "RESOURCE_EXHAUSTED" in err_msg
                        or "NOT_FOUND" in err_msg
                        or "404" in err_msg
                    ):
                        time.sleep(2 * (attempt + 1))
                        continue
                    break

        if last_err:
            raise last_err
        raise RuntimeError("Evaluation failed: no model response")
