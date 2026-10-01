Getting started
===============

Install
-------

From PyPI:

.. code-block:: bash

   pip install prism-compiler

Or from source (requires a Rust toolchain, ``rustup``):

.. code-block:: bash

   pip install git+https://github.com/Yale-QCS/prism

Or install a pre-built wheel from the
`releases page <https://github.com/Yale-QCS/prism/releases>`_
(no build dependencies needed).

Verify
------

Compile a 4-qubit GHZ circuit onto a 2x4 grid with PRISM:

.. jupyter-execute::

   from qiskit import QuantumCircuit
   from qiskit.transpiler import CouplingMap

   from prism.encodings import DualRail
   from prism.pipeline import build_pm

   qc = QuantumCircuit(4)
   qc.h(0)
   for i in range(3):
       qc.cx(i, i + 1)

   pm = build_pm(CouplingMap.from_grid(2, 4), enc=DualRail, seed=42)
   routed = pm.run(qc)
   print(pm.property_set["circuit_metrics"])
