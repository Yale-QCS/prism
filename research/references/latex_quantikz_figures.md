---
name: reference_latex_quantikz_figures
description: "Building TikZ/quantikz figures for the dual-rail paper (delocal_dualrail) — quantikz embedding, row-sep pitfall, alignment, layout discipline, build loop"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 2f87a8c0-fbe0-4b25-aa83-0612bfb9c1b5
---

Lessons from Fig. 1 (`delocal_dualrail/figures/prism_overview.tex`). Apply to the remaining ~14 figure slots.

**Quantikz is available**: preamble loads `\usetikzlibrary{quantikz2}` (not a `\usepackage`). Embed a circuit inside an outer tikzpicture as a node: `\node {\scalebox{0.75}{\begin{quantikz}[...]...\end{quantikz}}};`. To color the whole circuit (wires + gate borders + control dots + text) wrap the env in `{\color{beamX} ... }`. Controls: `\ctrl{n}` filled, `\octrl{n}` open; `n` = signed row offset to the target `\gate{...}` (both must be in the SAME column to connect vertically).

**Row-sep is the #1 trap**: `row sep={0.2cm,between origins}` is far too tight — the `R_z` gate box (~0.55cm tall) overflows vertically across neighboring wires and visually swallows the control dot (looks like "a bare rectangle, no control"). Use ~`0.4cm` between origins. 0.6cm reads as stretched/sparse. Sweet spot 0.4cm.

**Aligning several circuits in a row**: anchor by `anchor=north` at a common top y, NOT by center. A gate on row 3 vs row 4 changes each circuit's bounding-box height, so center-anchoring misaligns the wires. North-anchoring lines up the top wire (hence all wires, since spacing is identical). Connect dispersing lines to `(rk.north)`, outgoing arrows from `(rk.south)`.

**Uniform outgoing arrows when circuits have unequal height**: north-anchoring fixes the tops but the bottoms still differ — a circuit with its gate on the last row extends ~half a gate-box lower than one with the gate higher, so arrows from `(rk.south)` come out unequal (short ones render as just an arrowhead). Do NOT try to equalize by adding an invisible `\gate[...]{\vphantom{}}` on the empty row — ANY gate (even `draw=none,fill=none,inner xsep=0pt,minimum width=0pt`) splits the wire at that cell, leaving a visible gap in the wire (looks like a stray gate). A baseline depth strut is also fragile (font-metric dependent). The clean fix: start every arrow at the DEEPEST circuit's `.south` level and end at the routing box, so all arrows are identical length: `(rk.south |- r2.south) -- (rk.south |- phys.north)` where r2 is one of the deep (gate-on-last-row) circuits. Shallower circuits get a tiny gap above their arrow, which reads as spacing; pinning the start to the deepest `.south` (not an arbitrary lower fan line) keeps that gap minimal. Note: with quantikz gate-on-different-rows there's an irreducible ~half-gate-box height asymmetry — it has to surface somewhere (top-wire misalign, arrow-length, or a gap); equal-length arrows with a minimal gap is the least-bad and what the user accepted.

**Box padding**: acmart `\footnotesize` boxes look too tall with the default `inner sep=3pt` + `minimum height=7mm`. Snugger: `inner ysep=2.5pt, minimum height=5.5mm` (keep `minimum width` to fix the box width). The user notices a few pt of excess vertical padding.

**Layout discipline (the user cares a lot — thinks in PowerPoint "align & distribute")**: do NOT hand-type per-element coordinates; that always reads as clunky/uneven. Use the `positioning` library with ONE shared `node distance=<gap>` and place every element `below=of <prev>`, so all edge-gaps are identical (= vertical distribute). Make the non-box elements (opnode circuit, the prism glyph, the whole realization row) sizing nodes IN THE SAME CHAIN: e.g. `\node[below=of op, minimum width=9mm, minimum height=5.5mm, inner sep=0] (prism){};` then draw the triangle to `(prism.north)/(prism.south west)/(prism.south east)`; `\node[below=of prism, minimum height=11.5mm, inner sep=0] (rrow){};` then place the 4 circuits with `anchor=north at ($(rrow.north)+(\pm x,0)$)`. Beams run `(prism.south) -- (rk.north)`, feed-arrows `(rk.south |- rrow.south) -- (rk.south |- phys.north)`. This makes the beams and the feed-arrows occupy the SAME uniform gap as every box-to-box arrow, and the feed-arrows come out equal length automatically (size `rrow`'s `minimum height` to the deepest circuit). One standard box size for every `stage` box (identical `minimum width`).

**Width / whitespace**: the figure's rendered width = its widest ink. A full-width decorative rule (e.g. a dashed "lowering boundary" line spanning the page) inflates the bbox and forces whitespace in the column — trim such lines to the actual content span. Keep the wide elements (here the 4 dispersed realization circuits) as the width budget and bound everything else to them.

**Build + inspect loop**: `cd delocal_dualrail && latexmk -pdf -interaction=nonstopmode main_acm.tex` (the Bash cwd resets between calls, so `cd` every time; PDF lands at repo root, not `build/`). Inspect with `pdftoppm -png -r 400 -f 1 -l 1 main_acm.pdf /tmp/x` then `convert /tmp/x-01.png -crop WxH+X+Y /tmp/zoom.png` and Read the crop. Prototype tricky circuit syntax in a `/tmp` standalone (`\documentclass{standalone}`) to iterate fast without rebuilding the 20-page paper.

Physics constraints for dual-rail CRZ realizations live in [[project_realization_corrections]]: control on a_0 = open control, target on b_1 = `R_z(-θ)` (codeword {|01>,|10>}).
