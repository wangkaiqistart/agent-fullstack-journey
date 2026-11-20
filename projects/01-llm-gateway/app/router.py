"""按能力、逻辑模型和优先级选择 Provider。"""

from .config import GatewayConfig
from .providers import ProviderAdapter


class ModelRouter:
    def __init__(self, config: GatewayConfig, providers: dict[str, ProviderAdapter]):
        self.config = config
        self.providers = providers

    def candidates(self, logical_model: str, required: set[str]) -> list[ProviderAdapter]:
        names = self.config.model_routes.get(logical_model)
        if names is None:
            raise ValueError("unknown_model:" + logical_model)
        candidates = [self.providers[name] for name in names if name in self.providers]
        candidates = [provider for provider in candidates if required <= provider.capabilities]
        if not candidates:
            raise ValueError("no_compatible_provider:" + logical_model)
        return sorted(candidates, key=lambda provider: self.config.providers[provider.name].priority)
