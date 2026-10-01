"""Sphinx configuration for the PRISM documentation site."""

import inspect
from importlib import import_module
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

project = "PRISM"

release = _pkg_version("prism-compiler")
version = ".".join(release.split(".")[:2])
html_title = f"{project} {release}"
html_show_copyright = False

extensions = [
    "qiskit_sphinx_theme",
    "sphinx_copybutton",
    "sphinx.ext.intersphinx",
    "sphinx.ext.linkcode",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "jupyter_sphinx",
    "myst_parser",
    "sphinx.ext.napoleon",
    "sphinx.ext.githubpages",
    "sphinx_sitemap",
]

autosummary_generate = True
# Render defaults as written, not their expanded values.
autodoc_preserve_defaults = True
autodoc_typehints = "description"
autoclass_content = "both"

jupyter_execute_kwargs = {"allow_errors": False}

html_theme = "qiskit-ecosystem"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

html_theme_options = {
    "source_repository": "https://github.com/Yale-QCS/prism",
    "source_branch": "main",
    "source_directory": "docs/",
}

html_baseurl = "https://yale-qcs.github.io/prism/"
sitemap_url_scheme = "{link}"
sitemap_excludes = ["genindex.html", "search.html"]
exclude_patterns = ["_build", "**.ipynb_checkpoints"]

intersphinx_mapping = {
    "numpy": ("https://numpy.org/doc/stable/", None),
    "qiskit": (
        "https://quantum.cloud.ibm.com/docs/en/api/qiskit/",
        "https://quantum.cloud.ibm.com/docs/api/qiskit/objects.inv",
    ),
    "python": ("https://docs.python.org/3/", None),
}


_ROOT = Path(__file__).resolve().parent.parent


def linkcode_resolve(domain: str, info: dict[str, str]) -> str | None:
    """Link API objects to their Python source."""
    # One link per page: the documented class or function, not its members.
    if domain != "py" or "." in info["fullname"]:
        return None
    obj = getattr(import_module(info["module"]), info["fullname"], None)
    try:
        source = Path(inspect.getsourcefile(obj)).resolve().relative_to(_ROOT)
        line = inspect.getsourcelines(obj)[1]
    except (OSError, TypeError, ValueError):
        return None
    return f"https://github.com/Yale-QCS/prism/blob/main/{source}#L{line}"


def _hide_generated_source_links(
    _app: Any,
    pagename: str,
    _templatename: str,
    context: dict[str, Any],
    _doctree: Any,
) -> None:
    """Hide source links that would point to ignored autosummary stubs."""
    if pagename.startswith("apidocs/stubs/"):
        context["theme_source_repository"] = ""
        context["show_source"] = False


def setup(app: Any) -> None:
    """Register documentation-site callbacks."""
    app.connect("html-page-context", _hide_generated_source_links)
