"""Freeze benchmark circuits to QPY for the runners.

MQT Bench circuits are named with their requested widths; QASMBench files are
frozen at their own width with the ``_n<width>`` suffix stripped from the name.

  .venv/bin/python scripts/paper/freeze_circuits.py --mqt vbe_ripple_carry_adder:8,12,16
  .venv/bin/python scripts/paper/freeze_circuits.py --qasm artifacts/paper/manifests/qasmbench/*.qasm
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from qiskit import QuantumCircuit, qasm2, qpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_common import CODE_REPO  # noqa: E402

sys.path.insert(0, str(CODE_REPO / "src"))
from marabbecca.utils.benchmarks import _fetch_with_fallback  # noqa: E402

OUT = CODE_REPO / "artifacts/paper/manifests/circuits"


def _freeze(qc: QuantumCircuit, name: str, width: int) -> None:
    # Some library gates do not survive QPY; decompose until the file round-trips.
    for _ in range(5):
        buffer = io.BytesIO()
        qpy.dump(qc, buffer)
        buffer.seek(0)
        if qpy.load(buffer)[0] == qc:
            break
        qc = qc.decompose()
    else:
        raise RuntimeError(f"{name} does not round-trip through QPY")
    path = OUT / f"{name}_n{width}.qpy"
    with path.open("wb") as stream:
        qpy.dump(qc, stream)
    print(f"{path.relative_to(CODE_REPO)}: {qc.num_qubits} qubits, {qc.size()} ops")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mqt", nargs="*", default=[], help="name:w1,w2,...")
    parser.add_argument("--qasm", nargs="*", default=[], type=Path)
    args = parser.parse_args()
    for spec in args.mqt:
        name, widths = spec.split(":")
        for width in map(int, widths.split(",")):
            qc, _actual = _fetch_with_fallback(name, width)
            if qc is None:
                raise RuntimeError(f"MQT Bench has no {name} at or below {width}")
            _freeze(qc, name, width)
    for path in args.qasm:
        qc = qasm2.load(path, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
        _freeze(qc, re.sub(r"_n\d+$", "", path.stem), qc.num_qubits)


if __name__ == "__main__":
    main()
