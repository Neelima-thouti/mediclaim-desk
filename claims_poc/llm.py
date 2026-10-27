"""Thin wrapper around the model. Providers: mock (offline), openai, azure (Azure OpenAI / Foundry)."""
from __future__ import annotations

import json
import os
import time

from pydantic import BaseModel, ValidationError


class LLM:
    def __init__(self, mock: bool = False, provider: str | None = None, model: str | None = None):
        self.provider = "mock" if mock else (provider or os.getenv("LLM_PROVIDER", "openai"))
        self.mock = self.provider == "mock"
        self.calls: list[dict] = []  # per-call audit log: agent, seconds, token usage
        self.client = None
        self.model = model
        if self.provider == "azure":
            from openai import OpenAI
            endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")  # https://<resource>.openai.azure.com
            key = os.getenv("AZURE_OPENAI_API_KEY")
            if not key:  # Managed Identity / az login, no secret in config
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                key = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            self.client = OpenAI(base_url=f"{endpoint}/openai/v1/", api_key=key)
            self.model = model or os.environ["AZURE_OPENAI_DEPLOYMENT"]  # the DEPLOYMENT name, e.g. gpt-5.1
        elif self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    def run(self, agent: str, system: str, payload: dict, schema: type[BaseModel]) -> BaseModel:
        t0 = time.time()
        usage: dict = {}
        if self.mock:
            from .mock_handlers import HANDLERS
            result = schema.model_validate(HANDLERS[agent](payload))
        else:
            result, usage = self._call(system, payload, schema)
        self.calls.append({"agent": agent, "seconds": round(time.time() - t0, 2), "provider": self.provider, **usage})
        return result

    def _call(self, system: str, payload: dict, schema: type[BaseModel]):
        system = system + "\n\nReturn ONLY a JSON object that matches this JSON Schema:\n" + json.dumps(schema.model_json_schema())
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, default=str)}]
        extra = {}
        if os.getenv("LLM_REASONING_EFFORT"):  # reasoning models only, e.g. none / low / medium / high
            extra["reasoning_effort"] = os.environ["LLM_REASONING_EFFORT"]
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        last_error = None
        for _ in range(2):  # one retry with the validation error fed back to the model
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, response_format={"type": "json_object"}, **extra)
            if resp.usage:
                usage["prompt_tokens"] += resp.usage.prompt_tokens
                usage["completion_tokens"] += resp.usage.completion_tokens
            text = resp.choices[0].message.content
            try:
                return schema.model_validate_json(text), usage
            except ValidationError as e:
                last_error = e
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": f"Your JSON was invalid. Fix these errors and return JSON only:\n{e}"}]
        raise RuntimeError(f"Model output failed validation twice: {last_error}")
