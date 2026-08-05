Getting started
===============

Install
-------

From source (requires a Rust toolchain, ``rustup``):

.. code-block:: bash

   pip install git+https://github.com/evmckinney9/prism

Or install a pre-built wheel from the
`releases page <https://github.com/evmckinney9/prism/releases>`_
(no build dependencies needed).

Verify
------

.. code-block:: python

   from prism.main import Electron

   Electron().charge
