import os
from typing import Any, Dict, List

import requests
from langchain_core.messages import AIMessage, BaseMessage


class KimiChatModel:
    """Kimi chat model (Anthropic Messages-compatible gateway)."""

    def __init__(
        self,
        api_key: str = None,
        api_base: str = None,
        model: str = "kimi-k2.5",
        max_tokens: int = 8192,
        temperature: float = 1.0,
        request_timeout: int = 120,
        **kwargs,
    ):
        api_base = api_base or os.getenv("KIMI_API_BASE", "http://172.21.30.114:8020/v1")
        api_key = api_key or os.getenv("KIMI_API_KEY")
        if not api_key:
            raise ValueError(
                "Kimi API key is required. Set it via KIMI_API_KEY environment variable "
                "or pass it directly."
            )

        # 兼容透传配置（如 callbacks/verbose），不影响当前 HTTP 调用实现
        self.extra_config = dict(kwargs)
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.request_timeout = int(request_timeout)

    def _normalize_messages(self, messages: Any) -> tuple[str, List[Dict[str, str]]]:
        if not isinstance(messages, list):
            messages = [messages]

        system_parts: List[str] = []
        normalized: List[Dict[str, str]] = []
        for message in messages:
            if isinstance(message, BaseMessage):
                role = getattr(message, "type", "") or ""
                content = message.content if isinstance(message.content, str) else str(message.content)
            elif isinstance(message, dict):
                role = str(message.get("role", "user"))
                content = str(message.get("content", ""))
            else:
                role = "user"
                content = str(message)

            role = role.lower()
            if role in {"system"}:
                if content.strip():
                    system_parts.append(content.strip())
                continue
            if role in {"human"}:
                role = "user"
            if role in {"ai"}:
                role = "assistant"
            if role not in {"user", "assistant"}:
                role = "user"

            normalized.append({"role": role, "content": content})

        if not normalized:
            normalized = [{"role": "user", "content": ""}]
        return "\n".join(system_parts).strip(), normalized

    def _build_payload(self, messages: Any) -> Dict[str, Any]:
        system, normalized_messages = self._normalize_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": normalized_messages,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return payload

    def invoke(self, messages: Any, **kwargs):
        payload = self._build_payload(messages)
        if "max_tokens" in kwargs and kwargs["max_tokens"] is not None:
            payload["max_tokens"] = int(kwargs["max_tokens"])
        if "temperature" in kwargs and kwargs["temperature"] is not None:
            payload["temperature"] = float(kwargs["temperature"])
        if "model" in kwargs and kwargs["model"]:
            payload["model"] = str(kwargs["model"])

        url = f"{self.api_base}/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "anthropic-version": "2023-06-01",
        }
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.request_timeout,
        )
        if response.status_code >= 400:
            raise Exception(
                f"Kimi request failed: {response.status_code} {response.text}"
            )

        data = response.json()
        chunks = data.get("content") or []
        text_parts: List[str] = []
        for chunk in chunks:
            if isinstance(chunk, dict) and chunk.get("type") == "text":
                text_parts.append(str(chunk.get("text", "")))
        content = "".join(text_parts).strip()
        if not content:
            # 兜底：避免网关结构波动导致空响应
            content = str(data)
        return AIMessage(content=content)

    async def ainvoke(self, messages: Any, **kwargs):
        # 当前调用链路主要使用同步 invoke，异步路径先复用同步实现
        return self.invoke(messages, **kwargs)
