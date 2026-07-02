def __getattr__(name):
    if name == "print_dashboard":
        from .report import print_dashboard

        return print_dashboard
    raise AttributeError(name)


__all__ = ["print_dashboard"]
