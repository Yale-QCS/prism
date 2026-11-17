"""prism: a Qiskit transpiler for dual-rail encoded circuits."""

from importlib.metadata import version

from prism_qc.dualrail import ErasureCheck
from prism_qc.passes import SearchBudget
from prism_qc.pipeline import dualrail_pm, prism_stages

__all__ = ["ErasureCheck", "SearchBudget", "dualrail_pm", "prism_stages"]
__version__ = version("prism-qc")
