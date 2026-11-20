"""流式指标：TTFT、生成耗时和端到端耗时。"""

from dataclasses import dataclass
from time import monotonic


@dataclass
class StreamMetrics:
    started_at: float
    first_text_at: float | None = None
    finished_at: float | None = None

    @classmethod
    def start(cls) -> "StreamMetrics":
        return cls(monotonic())

    def observe_text(self):
        if self.first_text_at is None:
            self.first_text_at = monotonic()

    def finish(self):
        self.finished_at = monotonic()

    def as_dict(self) -> dict[str, float | None]:
        end = self.finished_at
        return {
            "ttft_ms": round((self.first_text_at - self.started_at) * 1000, 1)
            if self.first_text_at else None,
            "generation_ms": round((end - self.first_text_at) * 1000, 1)
            if end and self.first_text_at else None,
            "e2e_ms": round((end - self.started_at) * 1000, 1) if end else None,
        }

