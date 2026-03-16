"""
Django settings for test_brain project.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

TIME_ZONE = "Asia/Shanghai"
USE_TZ = False

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-your-secret-key-here")
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ["localhost", "127.0.0.1", "0.0.0.0", "172.16.32.88", "172.16.56.57", "172.21.30.105"],
)

ENABLE_MILVUS = env_bool("ENABLE_MILVUS", True)
MEDIA_ROOT = os.path.join(BASE_DIR, "uploads")
MEDIA_URL = "/uploads/"
CORS_ORIGIN_ALLOW_ALL = env_bool("CORS_ORIGIN_ALLOW_ALL", True)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.llm",
    "apps.agents",
    "apps.knowledge",
]

MIDDLEWARE = [
    "config.cors.SimpleCorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.mysql"),
        "NAME": os.getenv("DB_NAME", "test_brain_db"),
        "USER": os.getenv("DB_USER", "root"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
USE_I18N = True

STATIC_URL = "static/"
STATICFILES_DIRS = []
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LLM_PROVIDERS = {
    "default_provider": os.getenv("DEFAULT_LLM_PROVIDER", "qwen"),
    "deepseek": {
        "name": "DeepSeek",
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "api_base": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
        "temperature": env_float("DEEPSEEK_TEMPERATURE", 1.0),
        "max_tokens": env_int("DEEPSEEK_MAX_TOKENS", 8192),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
    },
    "qwen": {
        "name": "Qwen",
        "model": os.getenv("QWEN_MODEL", "qwen-max"),
        "api_base": os.getenv("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "temperature": env_float("QWEN_TEMPERATURE", 1.0),
        "max_tokens": env_int("QWEN_MAX_TOKENS", 8192),
        "api_key": os.getenv("QWEN_API_KEY", ""),
    },
    "kimi": {
        "name": "Kimi K2.5",
        "model": os.getenv("KIMI_MODEL", "kimi-k2.5"),
        "api_base": os.getenv("KIMI_API_BASE", "http://172.21.30.114:8020/v1"),
        "temperature": env_float("KIMI_TEMPERATURE", 1.0),
        "max_tokens": env_int("KIMI_MAX_TOKENS", 8192),
        "api_key": os.getenv("KIMI_API_KEY", ""),
    },
    "openai": {
        "name": "OpenAI",
        "model": os.getenv("OPENAI_MODEL", "gpt-5"),
        "temperature": env_float("OPENAI_TEMPERATURE", 0.7),
        "max_tokens": env_int("OPENAI_MAX_TOKENS", 200000),
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "api_base": os.getenv("OPENAI_API_BASE", ""),
    },
}

TEST_CASE_GENERATION_CONFIG = {
    "generation_temperature": env_float("TEST_CASE_GENERATION_TEMPERATURE", 0.3),
    "review_temperature": env_float("TEST_CASE_REVIEW_TEMPERATURE", 0.2),
    "default_target_count": env_int("TEST_CASE_DEFAULT_TARGET_COUNT", 8),
    "candidate_multiplier": env_int("TEST_CASE_CANDIDATE_MULTIPLIER", 2),
    "minimum_candidate_count": env_int("TEST_CASE_MINIMUM_CANDIDATE_COUNT", 8),
    "min_review_score": env_int("TEST_CASE_MIN_REVIEW_SCORE", 7),
    "max_supplement_rounds": env_int("TEST_CASE_MAX_SUPPLEMENT_ROUNDS", 2),
    "max_total_rounds": env_int("TEST_CASE_MAX_TOTAL_ROUNDS", 3),
    "dedupe_similarity_threshold": env_float("TEST_CASE_DEDUPE_SIMILARITY", 0.72),
    "keyword_overlap_threshold": env_float("TEST_CASE_KEYWORD_OVERLAP", 0.6),
}

VECTOR_DB_CONFIG = {
    "host": os.getenv("MILVUS_HOST", "127.0.0.1"),
    "port": os.getenv("MILVUS_PORT", "19530"),
    "collection_name": os.getenv("MILVUS_COLLECTION", "vv_rag_markdown_chunks"),
}

PLANE_CONFIG = {
    "base_url": os.getenv("PLANE_BASE_URL", ""),
    "workspace_slug": os.getenv("PLANE_WORKSPACE_SLUG", ""),
    "api_key": os.getenv("PLANE_API_KEY", ""),
    "allowed_states": ["积压", "未开始", "进行中", "开发阶段", "测试阶段"],
}

EMBEDDING_CONFIG = {
    "model": os.getenv("EMBEDDING_MODEL", "bge-m3"),
    "api_key": os.getenv("EMBEDDING_API_KEY", ""),
    "api_url": os.getenv("EMBEDDING_API_URL", "https://api-inference.huggingface.co/models/BAAI/bge-m3"),
}

os.environ["TOKENIZERS_PARALLELISM"] = os.getenv("TOKENIZERS_PARALLELISM", "false")
