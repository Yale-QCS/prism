"""Noiseless check: every routed+converted memory experiment fires no detector and no observable."""
import dataclasses, math, sys
from collections import Counter
import to_stim
from route import *
to_stim.DEVICE = dataclasses.replace(to_stim.DEVICE, t1=math.inf, dephasing=0.0,
    erasure={k: tuple(0.0 for _ in v) for k, v in to_stim.DEVICE.erasure.items()},
    pauli_z={k: tuple(0.0 for _ in v) for k, v in to_stim.DEVICE.pauli_z.items()})
fails, total = Counter(), Counter()
for code in sys.argv[1:] or ['steane', 'c832', 'five']:
    for rounds in [1, 2, 3]:
        mem = to_qiskit(experiment(code, rounds))
        topos = make_topologies(mem.qc.num_qubits)
        for topo in ['grid', 'hex_lattice', 'heavy_hex']:
            for arm in ARMS:
                for seed in [0, 100, 200]:
                    routed, m = compile_arm(mem.qc, topos[topo], arm, seed)
                    circ, _ = assemble(mem, routed)
                    d, o = circ.compile_detector_sampler().sample(200, separate_observables=True)
                    total[arm] += 1
                    fails[arm] += bool(d.any() or o.any())
for a in ARMS: print(a, f"{fails[a]}/{total[a]} fail")
