import os

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - optional runtime integration
    sentry_sdk = None


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn or sentry_sdk is None:
        return
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        environment=os.getenv("TRADING_MODE", "SIGNAL_ONLY"),
    )
