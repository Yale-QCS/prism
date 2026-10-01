API reference
=============

The public API of the :mod:`prism` package.

.. currentmodule:: prism

.. autosummary::
   :toctree: stubs/
   :nosignatures:

   encodings.QubitEncoding
   encodings.DualRail
   pipeline.build_pm
   logical.basic_logical_pm
   physical.physical_pm
   lowering.ir.LoweredOp
   lowering.commit.CommitPolicy
   lowering.commit.SearchBudget
   lowering.commit_policies.PrismRouting
   utils.metrics.CircuitMetrics
   utils.metrics.physical_depth
   utils.metrics.physical_duration
