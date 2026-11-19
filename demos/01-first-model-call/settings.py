"""只共用环境配置与错误出口，API 调用步骤留在各个示例中。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI


def create_client(prefix="AGENTOS_LLM"):
    # 按脚本位置定位，终端和 IDE 从任意目录运行均可。
    # 优先级：已有环境变量 > Demo 的 .env > 仓库根目录的 .env。
    demo_dir = Path(__file__).resolve().parent
    load_dotenv(demo_dir / ".env", override=False, interpolate=False)
    load_dotenv(demo_dir.parents[1] / ".env", override=False, interpolate=False)

    # 备用供应商使用 AGENTOS_ALT_LLM_*，原有示例保持默认配置。
    names = tuple(f"{prefix}_{suffix}" for suffix in ("BASE_URL", "API_KEY", "MODEL"))
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("缺少环境变量：" + ", ".join(missing))
    return OpenAI(
        base_url=os.environ[names[0]],
        api_key=os.environ[names[1]],
        timeout=60.0,
        max_retries=0,  # 学习时让一次请求对应一次结果，便于观察。
    ), os.environ[names[2]]


def run(main):
    try:
        main()
    except APIError as error:
        # 不打印可能带有请求内容的异常正文。
        status = getattr(error, "status_code", None)
        raise SystemExit(f"API 调用失败：{type(error).__name__}，HTTP {status or '未知'}") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None

