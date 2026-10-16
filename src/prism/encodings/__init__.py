"""``QubitEncoding`` contract + the concrete ``DualRail`` implementation."""

from prism.encodings.base import QubitEncoding
from prism.encodings.dualrail import DualRail, ErasureCheck

__all__ = ["DualRail", "ErasureCheck", "QubitEncoding"]
