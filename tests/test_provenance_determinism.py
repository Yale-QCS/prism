"""Same-seed determinism: identical output in one process and across fresh processes."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from qiskit import QuantumCircuit
from qiskit.passmanager import PropertySet
from qiskit.transpiler import CouplingMap

from prism.encodings import DualRail
from prism.pipeline import build_pm

SRC = Path(__file__).resolve().parents[1] / "src"


def canonical_hash(qc: QuantumCircuit) -> str:
    """Structural hash: op names, rounded params, qubit indices; independent of gate object ids."""
    h = hashlib.sha256()
    for ins in qc.data:
        params = [round(float(p), 9) for p in ins.operation.params]
        qubits = [qc.find_bit(q).index for q in ins.qubits]
        h.update(f"{ins.operation.name}{params}{qubits};".encode())
    return h.hexdigest()


def _bv8():
    """Idle-heavy n=8 BV (3-bit secret); tail placement wandered across processes before ``SeedVF2ErrorMap``."""
    qc = QuantumCircuit(8, 7)
    qc.x(0)
    qc.h(range(1, 8))
    for q in (2, 4, 6):
        qc.cz(0, q)
    qc.h(range(1, 8))
    qc.measure(range(1, 8), range(7))
    return qc


def _compile_canon(qc, seed=42):
    pm = build_pm(CouplingMap.from_grid(5, 4), enc=DualRail, seed=seed)
    ps = PropertySet()
    out = pm.run(qc, property_set=ps)
    m = ps["circuit_metrics"]
    return canonical_hash(out), (m.swaps, m.depth, m.active_gates)


def test_same_process_replay():
    """Two same-seed compiles in one process agree byte-for-byte."""
    (h1, m1), (h2, m2) = _compile_canon(_bv8()), _compile_canon(_bv8())
    assert h1 == h2
    assert m1 == m2


_SUBPROCESS_SNIPPET = """
import sys, json
sys.path.insert(0, {src!r})
from tests.test_provenance_determinism import _bv8, _compile_canon
h, m = _compile_canon(_bv8())
print(json.dumps([h, m]))
"""


def test_fresh_process_replay():
    """Two same-seed compiles in fresh processes agree byte-for-byte."""
    outs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", _SUBPROCESS_SNIPPET.format(src=str(SRC))],
            capture_output=True,
            text=True,
            check=True,
        )
        outs.append(json.loads(proc.stdout.strip().splitlines()[-1]))
    assert outs[0] == outs[1]
