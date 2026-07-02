from __future__ import annotations

import json
from pathlib import Path

import config
from strategies.factory import STRATEGY_REGISTRY


ALLOCATOR_REPORT_PATH = Path("research_results/multi_strategy/latest_multi_strategy_report.json")
RESEARCH_ONLY_STRATEGIES = {getattr(config, "ORB_PBC_STRATEGY_NAME", "orb_pullback_continuation_v1")}


def apply_strategy_allocator() -> dict:
    decision = select_strategy_for_cycle()
    selected_strategy = decision.get("selected_strategy")
    if selected_strategy and selected_strategy != config.ACTIVE_STRATEGY:
        config.ACTIVE_STRATEGY = selected_strategy
        if selected_strategy == config.ORVWAP_STRATEGY_NAME:
            config.TRADE_SYMBOLS = list(config.ORVWAP_TRADE_SYMBOLS)
        else:
            symbols = decision.get("symbols") or _default_symbols()
            config.TRADE_SYMBOLS = [symbol.upper() for symbol in symbols]
    return decision


def select_strategy_for_cycle(report_path: str | Path | None = None) -> dict:
    if not getattr(config, "AUTO_STRATEGY_SELECTION", False):
        return _decision("disabled", config.ACTIVE_STRATEGY, "AUTO_STRATEGY_SELECTION is false.")

    if config.TRADING_MODE == "LIVE":
        return _decision("blocked", config.ACTIVE_STRATEGY, "Auto strategy selection is disabled in LIVE mode.")

    if config.TRADING_MODE != "PAPER":
        return _decision("blocked", config.ACTIVE_STRATEGY, f"Unsupported trading mode for allocator: {config.TRADING_MODE}.")

    path = Path(report_path or ALLOCATOR_REPORT_PATH)
    if not path.exists():
        return _decision("fallback", config.ACTIVE_STRATEGY, f"No allocator report found at {path}.")

    with open(path, "r", encoding="utf-8") as file:
        report = json.load(file)

    allocator = report.get("strategy_allocator", {})
    symbols_by_strategy = report.get("symbols_by_strategy", {})
    mode = allocator.get("mode")
    selected_strategy = allocator.get("selected_strategy")

    if mode == "PAPER_CANDIDATE" and _is_executable_strategy(selected_strategy):
        return _decision(
            "selected",
            selected_strategy,
            allocator.get("reason", "Allocator selected a paper candidate."),
            allocator_mode=mode,
            symbols=symbols_by_strategy.get(selected_strategy),
        )

    if getattr(config, "AUTO_STRATEGY_USE_SHADOW_LEADER", False):
        leader = allocator.get("leader") or (report.get("leaderboard") or [{}])[0]
        leader_name = leader.get("strategy_name")
        if _is_executable_strategy(leader_name):
            return _decision(
                "shadow_selected",
                leader_name,
                f"Using shadow leader because AUTO_STRATEGY_USE_SHADOW_LEADER is true. {allocator.get('reason', '')}".strip(),
                allocator_mode=mode,
                symbols=symbols_by_strategy.get(leader_name),
            )

    return _decision(
        "fallback",
        config.ACTIVE_STRATEGY,
        allocator.get("reason", f"Allocator mode {mode or 'unknown'} did not produce an executable paper candidate."),
        allocator_mode=mode,
    )


def _is_executable_strategy(strategy_name: str | None) -> bool:
    if not strategy_name or strategy_name in RESEARCH_ONLY_STRATEGIES:
        return False
    strategy_class = STRATEGY_REGISTRY.get(strategy_name)
    if strategy_class is None:
        return False
    strategy = strategy_class()
    return callable(getattr(strategy, "evaluate_entry", None)) and callable(getattr(strategy, "evaluate_exit", None))


def _decision(status: str, selected_strategy: str | None, reason: str, *, allocator_mode: str | None = None, symbols: list[str] | None = None) -> dict:
    return {
        "status": status,
        "selected_strategy": selected_strategy,
        "allocator_mode": allocator_mode,
        "reason": reason,
        "symbols": symbols,
    }


def _default_symbols() -> list[str]:
    return list(getattr(config, "ORVWAP_TRADE_SYMBOLS", [])) or ["AAPL", "MSFT", "NVDA", "AMD", "META", "TSLA", "AMZN"]
