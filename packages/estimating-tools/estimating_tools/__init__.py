"""Deterministic construction estimating and engineering tools."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("estimating_tools")
except PackageNotFoundError:  # running from source without an install
    __version__ = "0.0.0+unknown"
