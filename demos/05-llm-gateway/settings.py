"""Gateway 的模型配置；密钥只从环境变量读取。"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str


def load_settings() -> dict[str, ProviderConfig]:
    demo_dir = Path(__file__).resolve().parent
    load_dotenv(demo_dir / ".env", override=False, interpolate=False)
    load_dotenv(demo_dir.parents[1] / ".env", override=False, interpolate=False)

    def read(prefix: str, *, required: bool) -> ProviderConfig | None:
        values = {key: os.environ.get(f"{prefix}_{key}", "").strip() for key in ("BASE_URL", "API_KEY", "MODEL")}
        if not all(values.values()):
            if required:
                missing = [f"{prefix}_{key}" for key, value in values.items() if not value]
                raise ValueError("缺少环境变量：" + ", ".join(missing))
            return None
        return ProviderConfig(prefix.lower(), values["BASE_URL"], values["API_KEY"], values["MODEL"])

    primary = read("AGENTOS_LLM", required=True)
    backup = read("AGENTOS_ALT_LLM", required=False)
    result = {"primary": primary}
    if backup:
        result["backup"] = backup
    return result
