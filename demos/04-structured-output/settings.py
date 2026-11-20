"""Structured Output Demo 共用的真实模型配置。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI


def create_client(prefix="AGENTOS_LLM"):
    demo_dir = Path(__file__).resolve().parent
    load_dotenv(demo_dir / ".env", override=False, interpolate=False)
    load_dotenv(demo_dir.parents[1] / ".env", override=False, interpolate=False)
    names = tuple(f"{prefix}_{suffix}" for suffix in ("BASE_URL", "API_KEY", "MODEL"))
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("缺少环境变量：" + ", ".join(missing))
    return OpenAI(
        base_url=os.environ[names[0]],
        api_key=os.environ[names[1]],
        timeout=60.0,
        max_retries=0,
    ), os.environ[names[2]]


def run(main):
    try:
        main()
    except APIError as error:
        status = getattr(error, "status_code", None)
        raise SystemExit(f"API 调用失败：{type(error).__name__}，HTTP {status or '未知'}") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
