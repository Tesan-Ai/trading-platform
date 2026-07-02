def ai_daily_summary(bot_run_id: int | None = None) -> dict:
    return {
        "enabled": False,
        "bot_run_id": bot_run_id,
        "summary": "AI summaries are intentionally disabled until observability and paper trading are validated.",
    }


def ai_trade_explanation(trade_id: int) -> dict:
    return {
        "enabled": False,
        "trade_id": trade_id,
        "explanation": "AI trade explanations are placeholders only and cannot place or modify trades.",
    }


def ai_risk_review(bot_run_id: int | None = None) -> dict:
    return {
        "enabled": False,
        "bot_run_id": bot_run_id,
        "review": "AI risk reviews are placeholders only and cannot bypass the risk engine.",
    }
