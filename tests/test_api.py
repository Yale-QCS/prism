"""The public API: submodules with ``__all__``; the package itself holds only ``__version__``."""

import importlib
import importlib.metadata

import pytest

import prism


@pytest.mark.parametrize(
    "module",
    ["prism.pipeline", "prism.ir", "prism.routing", "prism.encodings", "prism.metrics"],
)
def test_public_names_import(module):
    mod = importlib.import_module(module)
    assert mod.__all__ and all(hasattr(mod, name) for name in mod.__all__)


def test_package_has_a_version():
    assert prism.__version__ == importlib.metadata.version("prism-compiler")
