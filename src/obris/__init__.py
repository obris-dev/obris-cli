try:
    from importlib.metadata import version

    __version__ = version("obris-cli")
except Exception:
    __version__ = "dev"
