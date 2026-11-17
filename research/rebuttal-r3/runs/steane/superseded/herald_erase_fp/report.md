
**X memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0971 | 0.0749 | 22.9 [14.6, 31.3] | 17/1/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7251 → 0.6336 | 50,000 |
| (a) ideal per-site flags, noise `table4` | 0.0930 | 0.0691 | 25.7 [18.5, 32.3] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (b) flags at readout only, noise `table4` | 0.3051 | 0.2289 | 25.0 [18.6, 31.4] | 20/0/0 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `table4` | 0.6202 | 0.4824 | 22.2 [16.1, 27.6] | 17/0/3 | 84.55 → 48.90 | 20.78 → 17.27 | 1.0116 → 0.8664 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `table4` | 0.8547 | 0.6554 | 23.3 [18.8, 27.1] | 19/0/1 | 83.40 → 52.20 | 26.10 → 20.50 | 1.1181 → 0.9493 | 200,000 |

**Z memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0965 | 0.0649 | 32.7 [24.6, 40.7] | 19/1/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7336 → 0.6280 | 50,000 |
| (a) ideal per-site flags, noise `table4` | 0.0929 | 0.0693 | 25.4 [17.1, 32.8] | 18/0/2 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (b) flags at readout only, noise `table4` | 0.3024 | 0.2152 | 28.8 [23.8, 33.9] | 20/0/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `table4` | 0.6106 | 0.4810 | 21.2 [14.0, 27.4] | 17/0/3 | 81.30 → 52.55 | 20.87 → 17.42 | 1.0080 → 0.8883 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `table4` | 0.6720 | 0.5391 | 19.8 [14.3, 24.7] | 19/0/1 | 74.85 → 48.30 | 23.59 → 20.24 | 1.0627 → 0.9429 | 200,000 |
