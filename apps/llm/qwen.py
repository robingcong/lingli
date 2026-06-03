from langchain_community.chat_models import ChatOpenAI
import os


class QwenChatModel(ChatOpenAI):
    """Qwen chat model."""

    def __init__(
        self,
        api_key: str = None,
        api_base: str = None,
        model: str = "qwen3.7-max",
        **kwargs,
    ):
        api_base = api_base or os.getenv("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        api_key = api_key or os.getenv("QWEN_API_KEY")
        if not api_key:
            raise ValueError(
                "Qwen API key is required. Set it via QWEN_API_KEY environment variable "
                "or pass it directly."
            )

        os.environ["OPENAI_API_KEY"] = api_key

        super().__init__(
            model_name=model,
            openai_api_base=api_base,
            **kwargs,
        )
