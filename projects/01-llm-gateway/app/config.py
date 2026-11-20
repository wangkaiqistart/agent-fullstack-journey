"""YAML 配置和环境变量读取。"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    priority: int
    capabilities: frozenset[str]


@dataclass(frozen=True)
class GatewayConfig:
    providers: dict[str, ProviderConfig]
    model_routes: dict[str, list[str]]
    required_capabilities: dict[str, set[str]]
    max_attempts: int


_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value: str) -> str:
    return _ENV.sub(lambda match: os.environ.get(match.group(1), ""), value)


def load_config(path: str | Path) -> GatewayConfig:
    config_path = Path(path)
    load_dotenv(config_path.parent / ".env", override=False, interpolate=False)
    load_dotenv(config_path.parents[2] / ".env", override=False, interpolate=False)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    providers = {}
    for item in raw.get("providers", []):
        base_url = _expand(str(item.get("base_url", ""))).strip()
        api_key = os.environ.get(str(item.get("api_key_env", "")), "").strip()
        model = _expand(str(item.get("model", ""))).strip()
        if not (base_url and api_key and model):
            continue
        providers[item["name"]] = ProviderConfig(
            name=item["name"],
            base_url=base_url,
            api_key=api_key,
            model=model,
            priority=int(item.get("priority", 100)),
            capabilities=frozenset(item.get("capabilities", [])),
        )
    routes = {name: list(value.get("providers", [])) for name, value in raw.get("models", {}).items()}
    required = {name: set(value.get("required_capabilities", [])) for name, value in raw.get("models", {}).items()}
    retry = raw.get("retry", {})
    return GatewayConfig(providers, routes, required, int(retry.get("max_attempts", 2)))
