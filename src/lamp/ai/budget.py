"""Monthly AI spend ledger (append-only JSONL)."""
import json
from datetime import date
from pathlib import Path
from typing import Callable


# USD per million tokens: (input, cached input, output).
# developers.openai.com/api/docs/pricing, 2026-10-25. Reasoning tokens bill as output.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-6-luna": (0.10, 0.01, 0.50),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6-astra": (10.00, 1.00, 50.00),
}
_WORST = tuple(max(p[i] for p in PRICES.values()) for i in range(3))


class Budget:
    def __init__(self, path: Path, monthly_cap_usd: float, today: Callable[[], date] = date.today):
        self._path = path
        self.cap = monthly_cap_usd
        self._today = today

    def record(self, model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        p_in, p_cached, p_out = PRICES.get(model, _WORST)
        cost = ((input_tokens - cached_tokens) * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1e6
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps({"date": self._today().isoformat(), "model": model, "cost": cost,
                                "in": input_tokens, "cached": cached_tokens, "out": output_tokens}) + "\n")
        return cost

    def month_to_date(self) -> float:
        month = self._today().strftime("%Y-%m")
        total = 0.0
        try:
            lines = self._path.read_text().splitlines()
        except OSError:
            return 0.0
        for line in lines:
            try:
                row = json.loads(line)
                if row["date"].startswith(month):
                    total += float(row["cost"])
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        return total

    def remaining(self) -> float:
        return max(0.0, self.cap - self.month_to_date())

    def can_spend(self, estimate_usd: float = 0.0) -> bool:
        return self.month_to_date() + estimate_usd < self.cap

    def status(self) -> dict:
        spent = self.month_to_date()
        return {"spent": spent, "cap": self.cap, "blocked": spent >= self.cap}
