"""DeepSeek Chat Completions adapter for grounded answer generation."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from dotenv import load_dotenv

from src.generation.rag import Citation


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
Transport = Callable[[urllib.request.Request, float], bytes]


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 60.0
    max_tokens: int = 800

    @classmethod
    def from_environment(
        cls,
        *,
        default_base_url: str = DEFAULT_BASE_URL,
        default_model: str = DEFAULT_MODEL,
    ) -> "DeepSeekSettings":
        load_dotenv()
        api_key = (
            os.getenv("DEEPSEEK_API_KEY", "").strip()
            or os.getenv("LLM_API_KEY", "").strip()
        )
        if not api_key:
            raise ValueError(
                "缺少DeepSeek密钥：请在.env中设置DEEPSEEK_API_KEY或LLM_API_KEY"
            )
        return cls(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", default_base_url).strip()
            or default_base_url,
            model=os.getenv("LLM_MODEL", default_model).strip() or default_model,
        )


class DeepSeekGenerator:
    name = "deepseek"

    def __init__(
        self,
        settings: DeepSeekSettings,
        *,
        transport: Transport = _urlopen_transport,
    ):
        self.settings = settings
        self.transport = transport

    def generate(
        self,
        *,
        question: str,
        prompt: str,
        citations: list[Citation],
    ) -> str:
        del question, citations
        endpoint = f"{self.settings.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是严谨的上市公司年报问答助手。"
                        "只能依据用户消息中的证据回答，并严格保留证据编号。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": self.settings.max_tokens,
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            raw = self.transport(request, self.settings.timeout_seconds)
            response = json.loads(raw.decode("utf-8"))
            answer = str(response["choices"][0]["message"]["content"]).strip()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"DeepSeek API返回HTTP {exc.code}：{details}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API连接失败：{exc.reason}") from exc
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("DeepSeek API返回格式无效") from exc
        if not answer:
            raise RuntimeError("DeepSeek API返回空答案")
        return answer
