from contextlib import contextmanager

import config


@contextmanager
def temporary_config(overrides: dict):
    original_values = {}

    for key, value in overrides.items():
        original_values[key] = getattr(config, key)
        setattr(config, key, value)

    try:
        yield
    finally:
        for key, value in original_values.items():
            setattr(config, key, value)
