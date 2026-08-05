## prism

[![CI](https://github.com/evmckinney9/prism/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/evmckinney9/prism/actions/workflows/ci.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/prism)](https://pypi.org/project/prism/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/evmckinney9/prism/blob/main/src/notebooks/01_main.ipynb)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/evmckinney9/prism)
<!-- Uncomment after enabling Zenodo archiving (see .github/CONTRIBUTING.md), using the concept DOI it mints: -->
<!-- [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX) -->

transpiler for dual-rail multi-realization gate sets

**[Documentation](https://evmckinney9.github.io/prism/)** | **[Paper](https://arxiv.org/abs/XXXX.XXXXX)**

______

```bash
pip install prism
```

Or from source (requires a Rust toolchain): `pip install git+https://github.com/evmckinney9/prism`

```python
from prism.main import Electron

Electron().charge
```

<!-- When tutorials outgrow the one starter notebook, move user-facing
     notebooks into docs/ (rendered by nbsphinx) and repoint the Colab badge
     there; src/notebooks/ stays for development scratch. -->

> [!IMPORTANT]
> This software is provided as-is with no guarantee of support or maintenance. Bug reports and pull requests are welcome, but there is no commitment to respond or resolve issues on any timeline.
