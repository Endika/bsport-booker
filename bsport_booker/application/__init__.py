"""The use cases. They know the ports and the domain, and nothing about HTTP or files."""

from .tick import Mode, Tick

__all__ = ["Mode", "Tick"]
