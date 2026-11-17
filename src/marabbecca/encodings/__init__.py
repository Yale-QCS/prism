"""``QubitEncoding`` contract + concrete implementations (DualRail, RepCode, Iceberg412)."""

from marabbecca.encodings.base import QubitEncoding
from marabbecca.encodings.dualrail import DualRail
from marabbecca.encodings.iceberg import Iceberg412
from marabbecca.encodings.repcode import RepCode

__all__ = ["DualRail", "Iceberg412", "QubitEncoding", "RepCode"]
