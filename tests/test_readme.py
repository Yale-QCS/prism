"""The README's Python examples run, and its drawings are the quickstart's circuits.

``PRISM_UPDATE_README=1 pytest tests/test_readme.py`` rewrites the drawings.
"""

import os
import re
from pathlib import Path

README = Path(__file__).parents[1] / "README.md"


def test_readme_examples_run_and_drawings_are_current():
    text = README.read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert blocks
    namespace: dict = {}
    for k, block in enumerate(blocks):
        exec(block, namespace)
        if k == 0:  # the quickstart
            drawings = [
                str(namespace["qc"].draw(cregbundle=False)),
                str(namespace["out"].draw(idle_wires=False, fold=-1, cregbundle=False)),
            ]
            # As committed: the pre-commit hook strips trailing whitespace.
            drawings = [re.sub(r"[ \t]+$", "", d, flags=re.M) for d in drawings]
    shown = iter(drawings)
    current = re.sub(
        r"```text\n.*?```", lambda _: f"```text\n{next(shown)}\n```", text, flags=re.S
    )
    if os.environ.get("PRISM_UPDATE_README"):
        README.write_text(current)
        return
    assert current == text, (
        "README drawings are stale: run PRISM_UPDATE_README=1 pytest tests/test_readme.py"
    )
