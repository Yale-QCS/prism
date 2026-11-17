
**X memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0971 | 0.0749 | 22.9 [14.6, 31.3] | 17/1/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7251 → 0.6336 | 50,000 |
| (a) ideal per-site flags, noise `full` | 0.3134 | 0.2617 | 16.5 [11.4, 21.5] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7928 → 0.7013 | 200,000 |
| (b) flags at readout only, noise `full` | 0.7336 | 0.5830 | 20.5 [16.3, 24.7] | 20/0/0 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7928 → 0.7013 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `full` | 0.8006 | 0.6438 | 19.6 [14.7, 23.8] | 18/0/2 | 84.55 → 48.90 | 20.78 → 17.27 | 1.0796 → 0.9344 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `full` | 1.0416 | 0.8169 | 21.6 [17.6, 25.0] | 19/0/1 | 83.40 → 52.20 | 26.10 → 20.50 | 1.1861 → 1.0173 | 200,000 |
| (a) ideal per-site flags, noise `table4` | 0.0930 | 0.0691 | 25.7 [18.5, 32.3] | 18/0/2 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (b) flags at readout only, noise `table4` | 0.3726 | 0.2823 | 24.3 [18.8, 29.9] | 19/0/1 | 70.15 → 47.75 | 13.37 → 10.69 | 0.7248 → 0.6333 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `table4` | 0.6546 | 0.5139 | 21.5 [16.5, 25.9] | 18/0/2 | 84.55 → 48.90 | 20.78 → 17.27 | 1.0116 → 0.8664 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `table4` | 0.9042 | 0.6794 | 24.9 [20.8, 28.4] | 19/0/1 | 83.40 → 52.20 | 26.10 → 20.50 | 1.1181 → 0.9493 | 200,000 |

**Z memory, hexagonal lattice**

| Protocol | Greedy P_L (%) | PRISM P_L (%) | Relative reduction (%) [95%] | Seeds PRISM lower/equal/higher | SWAPs G → P | Duration (µs) G → P | Route score G → P | Shots per route |
|---|---|---|---|---|---|---|---|---|
| published Table II | 0.0965 | 0.0649 | 32.7 [24.6, 40.7] | 19/1/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7336 → 0.6280 | 50,000 |
| (a) ideal per-site flags, noise `full` | 0.3020 | 0.2443 | 19.1 [13.7, 24.2] | 19/0/1 | 78.50 → 48.90 | 13.59 → 10.52 | 0.8013 → 0.6957 | 200,000 |
| (b) flags at readout only, noise `full` | 0.5656 | 0.4430 | 21.7 [17.8, 25.3] | 19/0/1 | 78.50 → 48.90 | 13.59 → 10.52 | 0.8013 → 0.6957 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `full` | 1.0673 | 0.8947 | 16.2 [9.9, 21.6] | 18/0/2 | 81.30 → 52.55 | 20.87 → 17.42 | 1.0760 → 0.9563 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `full` | 1.1966 | 1.0048 | 16.0 [11.3, 20.5] | 19/0/1 | 74.85 → 48.30 | 23.59 → 20.24 | 1.1307 → 1.0109 | 200,000 |
| (a) ideal per-site flags, noise `table4` | 0.0929 | 0.0693 | 25.4 [17.1, 32.8] | 18/0/2 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (b) flags at readout only, noise `table4` | 0.2990 | 0.2108 | 29.5 [25.1, 33.9] | 20/0/0 | 78.50 → 48.90 | 13.59 → 10.52 | 0.7333 → 0.6277 | 200,000 |
| (c) compiled checks, rounds 1-2, noise `table4` | 0.6666 | 0.5321 | 20.2 [12.2, 26.8] | 17/0/3 | 81.30 → 52.55 | 20.87 → 17.42 | 1.0080 → 0.8883 | 200,000 |
| (c') compiled checks, all 3 rounds, noise `table4` | 0.7938 | 0.6399 | 19.4 [13.7, 24.5] | 19/0/1 | 74.85 → 48.30 | 23.59 → 20.24 | 1.0627 → 0.9429 | 200,000 |
