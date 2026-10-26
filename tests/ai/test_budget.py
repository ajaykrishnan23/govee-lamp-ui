from datetime import date

import pytest

from lamp.ai.budget import PRICES, Budget


def make(tmp_path, cap=10.0, today=date(2026, 10, 25)):
    holder = {"d": today}
    return Budget(tmp_path / "usage.jsonl", cap, today=lambda: holder["d"]), holder


def test_record_computes_cost(tmp_path):
    b, _ = make(tmp_path)
    # gpt-6-luna: $0.10 in, $0.01 cached, $0.50 out per million; cached tokens are part of input
    cost = b.record("gpt-6-luna", input_tokens=1_000_000, cached_tokens=200_000, output_tokens=100_000)
    assert cost == pytest.approx(0.8 * 0.10 + 0.2 * 0.01 + 0.1 * 0.50)
    assert b.month_to_date() == pytest.approx(cost)


def test_persists_across_instances(tmp_path):
    b, _ = make(tmp_path)
    b.record("gpt-6-luna", 1_000_000, 0, 0)
    b2, _ = make(tmp_path)
    assert b2.month_to_date() == pytest.approx(0.10)


def test_month_rollover_resets(tmp_path):
    b, holder = make(tmp_path, today=date(2026, 9, 30))
    b.record("gpt-6-luna", 1_000_000, 0, 0)
    holder["d"] = date(2026, 10, 1)
    assert b.month_to_date() == 0


def test_can_spend_false_at_cap(tmp_path):
    b, _ = make(tmp_path, cap=0.5)
    assert b.can_spend()
    b.record("gpt-6-luna", 0, 0, 1_000_000)  # $0.50
    assert not b.can_spend()
    assert b.status() == {"spent": pytest.approx(0.5), "cap": 0.5, "blocked": True}


def test_can_spend_with_estimate(tmp_path):
    b, _ = make(tmp_path, cap=1.0)
    b.record("gpt-6-luna", 0, 0, 1_000_000)  # $0.50
    assert b.can_spend(0.4) and not b.can_spend(0.6)


def test_unknown_model_uses_most_expensive_price(tmp_path):
    b, _ = make(tmp_path)
    worst_out = max(p[2] for p in PRICES.values())
    assert b.record("mystery-model", 0, 0, 1_000_000) == pytest.approx(worst_out)


def test_corrupt_line_ignored(tmp_path):
    b, _ = make(tmp_path)
    (tmp_path / "usage.jsonl").write_text("garbage\n")
    b.record("gpt-6-luna", 1_000_000, 0, 0)
    assert b.month_to_date() == pytest.approx(0.10)
