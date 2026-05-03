from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass
class LlmResponse:
    text: str
    raw: dict[str, Any]


class LlmClient:
    def __init__(self, api_base: str, api_key: str, model: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2, timeout: int = 180) -> LlmResponse:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY 未配置，请在 subtitle-agent/.env 中填写。")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.api_base}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"大模型 API 返回 HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"大模型 API 请求失败: {exc}") from exc

        choices = raw.get("choices", [])
        if not choices:
            raise RuntimeError("大模型 API 没有返回 choices。")
        message = choices[0].get("message", {})
        text = str(message.get("content", "")).strip()
        return LlmResponse(text=text, raw=raw)
