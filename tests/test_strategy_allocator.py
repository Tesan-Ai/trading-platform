import json

import config
from strategy_allocator import select_strategy_for_cycle


def test_allocator_selects_paper_candidate(tmp_path, monkeypatch):
    report_path = tmp_path / "allocator.json"
    report_path.write_text(
        json.dumps(
            {
                "strategy_allocator": {
                    "mode": "PAPER_CANDIDATE",
                    "selected_strategy": config.ORVWAP_STRATEGY_NAME,
                    "reason": "good enough",
                },
                "symbols_by_strategy": {
                    config.ORVWAP_STRATEGY_NAME: ["NVDA", "META"],
                },
            }
        )
    )
    monkeypatch.setattr("config.AUTO_STRATEGY_SELECTION", True)
    monkeypatch.setattr("config.TRADING_MODE", "PAPER")

    decision = select_strategy_for_cycle(report_path)

    assert decision["status"] == "selected"
    assert decision["selected_strategy"] == config.ORVWAP_STRATEGY_NAME
    assert decision["symbols"] == ["NVDA", "META"]


def test_allocator_blocks_live_mode(tmp_path, monkeypatch):
    report_path = tmp_path / "allocator.json"
    report_path.write_text(
        json.dumps(
            {
                "strategy_allocator": {
                    "mode": "PAPER_CANDIDATE",
                    "selected_strategy": config.ORVWAP_STRATEGY_NAME,
                }
            }
        )
    )
    monkeypatch.setattr("config.AUTO_STRATEGY_SELECTION", True)
    monkeypatch.setattr("config.TRADING_MODE", "LIVE")

    decision = select_strategy_for_cycle(report_path)

    assert decision["status"] == "blocked"
    assert decision["selected_strategy"] == config.ACTIVE_STRATEGY
