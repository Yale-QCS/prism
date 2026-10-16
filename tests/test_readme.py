"""The README's Python examples run, in order, in one namespace."""

import re
from pathlib import Path

README = Path(__file__).parents[1] / "README.md"


def test_readme_examples_run():
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(), re.S)
    assert blocks
    namespace: dict = {}
    for block in blocks:
        exec(block, namespace)
