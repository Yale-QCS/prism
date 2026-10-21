"""prism: a Qiskit transpiler for dual-rail encoded circuits."""

from importlib.metadata import version

from prism.dualrail import ErasureCheck
from prism.passes import SearchBudget
from prism.pipeline import dualrail_pm, prism_stages

__all__ = ["ErasureCheck", "SearchBudget", "dualrail_pm", "prism_stages"]
__version__ = version("prism-qc")
