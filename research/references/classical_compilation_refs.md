# Classical compilation references for the paper

Written 2026-06-10 (user request: ground the paper's framing in classical
compiler literature; seeds = "delayed commitment" and "the phase ordering
problem"). Six citation families, each with the canonical references and the
exact sentence-level mapping to our machinery. Venues marked because two of
the strongest anchors are MICRO papers. Exact titles spot-verified by web
search 2026-06-10; re-verify page numbers at bib time.

## 1. Delayed commitment / delayed binding (the user's seed; OUR HEADLINE TERM)

- Wulf, Johnsson, Weinstock, Hobbs, Geschke, *The Design of an Optimizing
  Compiler* (Elsevier, 1975). The BLISS-11 compiler has a literal DELAY
  phase: defer code-shape decisions (e.g., unary complement) until enough
  context exists to choose well.
- Leverett, Cattell, Hobbs, Newcomer, Reiner, Schatz, Wulf, "An Overview of
  the Production-Quality Compiler-Compiler Project," IEEE Computer 13(8),
  1980. PQCC organizes code generation around progressively delayed binding
  of representation decisions.
- Wulf & Nori, "Delayed Binding in PQCC Generated Compilers," CMU tech
  report, 1982 (DTIC ADA125935). The dedicated treatment.

**Mapping:** `LoweredOp` carrying the realization set across the lowering
boundary IS delayed binding of the logical-to-physical map; the commit
policy is the binding point. The strategy ladder is literally a
binding-time ladder: trivial binds at expansion, greedy at placement,
prism at routing. One sentence in Ch.5's intro names this lineage and
instantly tells a MICRO reviewer what the IR is for.

## 2. The phase ordering problem (the user's second seed)

- Vegdahl, "Phase coupling and constant generation in an optimizing
  microcode compiler," **MICRO-15, 1982**. The venue's own founding
  instance of the problem.
- Whitfield & Soffa, "An approach for exploring code improving
  transformations," TOPLAS 19(6), 1997 (earlier form 1990).
- Cooper, Schielke, Subramanian, "Optimizing for reduced code space using
  genetic algorithms," LCTES 1999 (search over phase orders).
- Kulkarni et al., "Practical exhaustive optimization phase order
  exploration and evaluation," TACO 2009; Kulkarni & Cavazos, "Mitigating
  the compiler optimization phase-ordering problem using machine learning,"
  OOPSLA 2012 (the ML era).

**Mapping:** logical -> lowering -> placement -> routing is a phase
decomposition, and the placement-dependent ISA is a phase-ordering
VIOLATION: a later phase (placement/routing) changes the legality and cost
of an earlier phase's decisions (which realization, whether a 1Q gate is
executable at all). Standard toolchains resolve the violation by
worst-casing (permanent co-location); the multi-realization IR resolves it
by deferral.

## 3. Register allocation vs instruction scheduling (the sharpest analogue)

- Goodman & Hsu, "Code scheduling and register allocation in large basic
  blocks," ICS 1988.
- Bradlee, Eggers, Henry, "Integrating register allocation and instruction
  scheduling for RISCs," ASPLOS 1991. NOTE (verified 2026-06-11): the
  "antagonistic optimizations" epigraph is NOT theirs. The verbatim source
  is Ambrosch, Ertl, Beer, Krall, "Dependence-conscious global register
  allocation," LNCS 782, pp. 125-136 (1994), abstract: "Register allocation
  and instruction scheduling are antagonistic optimizations: Whichever is
  applied first, it will impede the other." Bradlee 1991 stays cited as the
  empirical integration study only (refs.bib has ambrosch_dependence_1994).
- Pinter, "Register allocation with instruction scheduling: a new
  approach," PLDI 1993.
- Norris & Pollock, "An experimental study of several cooperative register
  allocation and instruction scheduling strategies," **MICRO-28, 1995**.
- Castañeda Lozano, Carlsson, Hjort Blindell, Schulte, "Combinatorial
  Register Allocation and Instruction Scheduling," TOPLAS 41(3), 2019
  (Unison; arXiv:1804.02452): the modern integrated/combinatorial endpoint.

**Mapping:** placement = allocation (spatial binding of program values to
physical resources), swaps = spills/copies (the cost of a binding under
pressure), realization selection = instruction selection. Greedy is the
phased pipeline (select, then place, then route); prism is the cooperative
form; AQORN/Jin are "allocation first." The inloop_evidence ledger (seven
same-budget placement-time interventions absorbed by the in-loop min) is
this literature's lesson reproduced in a quantum lowering stack.

## 4. Instruction selection as DAG tiling with multiple covers

- Aho, Ganapathi, Tjiang, "Code generation using tree matching and dynamic
  programming," TOPLAS 1989 (twig).
- Pelegrí-Llopart & Graham, "Optimal code generation for expression trees:
  an application of BURS theory," POPL 1988.
- Fraser, Hanson, Proebsting, "Engineering a simple, efficient
  code-generator generator," LOPLAS 1992 (iburg).
- Koes & Goldstein, "Near-optimal instruction selection on DAGs," CGO 2008.
- Hjort Blindell, *Instruction Selection: Principles, Methods, and
  Applications*, Springer 2016 (survey; arXiv:1306.4898).

**Mapping:** a logical gate's realization set = the applicable pattern/tile
set; AQORN's Table 1 is a cost-annotated tile table. The structural delta
that defines our contribution in this vocabulary: classical tile costs are
CONTEXT-FREE (a tile costs the same wherever it matches), so selection can
run before allocation; our realization costs are LAYOUT-DEPENDENT, so
selection forced before placement/routing is selection with made-up costs.
That is why the min must sit inside the router.

## 5. Equality saturation / e-graphs (the closest modern analogue to the IR)

- Tate, Stepp, Tatlock, Lerner, "Equality saturation: a new approach to
  optimization," POPL 2009.
- Willsey, Nandi, Wang, Flatt, Tatlock, Panchekha, "egg: Fast and
  extensible equality saturation," POPL 2021 (PACMPL 5).

**Mapping:** the e-graph answer to phase ordering is "do not pick; carry
ALL equivalent forms compactly and extract later against a global cost."
`LoweredOp` is exactly a one-level e-class over physical realizations, and
the front-layer min is the extraction step, with the routing state as the
cost model. Equality saturation is fashionable at systems venues (tensor
graph superoptimization), so this is the reference that makes the IR look
like a known-good design rather than an ad-hoc trick.

## 6. Iterative compilation / autotuning (what prism's trials are)

- Bodin, Kisuki, Knijnenburg, O'Boyle, Rohou, "Iterative compilation in a
  non-linear optimisation space," FDO workshop 1998.
- Whaley & Dongarra, "Automatically tuned linear algebra software" (ATLAS),
  SC 1998; Frigo & Johnson, "The design and implementation of FFTW3," Proc.
  IEEE 2005.

**Mapping:** prism's 16 trials x forward/backward iterations with best-of
selection = iterative compilation embedded in one pass; the empirical
finding that hand-crafted seeds lose to the search at equal budget is the
autotuning literature's standard lesson, reproduced.

## 7. Aggregate dissolution (the user's lowering picture, added 2026-06-10)

- Callahan, Carr, Kennedy, "Improving register allocation for subscripted
  variables," PLDI 1990 (scalar replacement). Muchnick, *Advanced Compiler
  Design and Implementation*, 1997 (scalar replacement of aggregates; the
  LLVM SROA pass is the deployed form). VERIFY exact attributions at bib
  time.
- Chow & Hennessy, "The priority-based coloring approach to register
  allocation," TOPLAS 1990; Cooper & Simpson, "Live range splitting in a
  graph coloring register allocator," CC 1998 (a source variable's
  one-register spatial identity dissolves into its def-use web).
- Leroy, "Unboxed objects and polymorphic typing," POPL 1992 (box only at
  uses that demand the box).

**Mapping:** the logical qubit is an aggregate of rails; its spatial
bundling is a representation property, not a physical one (the code couples
rail STATES, not positions). Correct lowering performs scalar replacement
on it: the boundary dissolves, and what survives is a free bookkeeping
entry (partition + Pauli frame) plus a demand pattern (non-diagonal 1Q
gates, checks) whose operations transiently re-materialize the aggregate.
Keeping the bundle alive without demand (Quotient-SABRE's fat nodes, every
logical SWAP = 2 physical) is the ghost-struct anti-pattern. The honest
criterion: the compiler must not IMPOSE bundling; the demand may (vqe_su2
stays bundled under prism, adjFrac 1.00, correctly; freedom circuits
dissolve to adjFrac 0.21-0.50). Precision flag for prose: only the SPATIAL
binding is removed; parity coupling and frame-tracked identity are
conserved semantics.

## 8. MLIR / multi-level IR design (read in full 2026-06-10, arXiv:2002.11054)

- Lattner, Amini, Bondhugula, Cohen, Davis, Pienaar, Riddle, Shpeisman,
  Vasilache, Zinenko, "MLIR: Scaling Compiler Infrastructure for Domain
  Specific Computation," CGO 2021 (arXiv:2002.11054).

The four design statements that map directly onto our machinery:

1. PROGRESSIVE LOWERING: lowering "performed in small steps along multiple
   abstraction levels," explicitly contrasted with rigid fixed-level
   pipelines (Open64 WHIRL's five levels, Clang's AST -> LLVM ->
   SelectionDAG -> MachineInstr); they state this "has deep implications on
   the phase ordering of transformations" and that pass roles (optimizing,
   enabling, lowering, cleanup) should mix "at the granularity of a single
   operation rather than sequencing passes on the full compilation unit."
   That last clause IS prism: the lowering decision (realization selection)
   executes per-operation inside the routing pass, not as a sequenced
   full-circuit pass.
2. MAINTAIN HIGHER-LEVEL SEMANTICS / CONSCIOUS LOSS: "attempts to raise
   semantics once lowered are fragile"; "the loss of structure is then
   conscious and happens only where the structure is no longer needed."
   Standard quantum pipelines lose the realization structure UNCONSCIOUSLY
   at the lowering boundary; LoweredOp makes the loss conscious and late
   (at commit, with the frame recorded). Also: "a part of the
   representation [may] remain in higher-level abstraction while another
   part is lowered": mid-routing, committed gates are physical while
   uncommitted LoweredOps are not; the mixed-level IR state is a named
   MLIR property, not an exotic trick.
3. RAISING IS FRAGILE (their 5.2.2): polyhedral raising from lowered form
   is "computationally hard"; keeping structure removes the need. Our
   concrete instance: O3's 2Q resynthesis re-derives unitaries across the
   code boundary and breaks restricted ISAs / transversal structure
   (PHYSICAL_RESYNTHESIS finding): recovery-by-resynthesis is exactly the
   fragile raising MLIR warns about.
4. THE ART OF ABSTRACTION DESIGN (their 6.4): "the 'art' of compiler IR
   design and abstraction design is not well understood... relatively few
   have had the opportunity to define the abstractions themselves."
   Positions an IR-design paper (what abstraction should cross the
   logical-to-physical boundary) as the under-studied research question,
   in MLIR's own words.

Minor legibility hook: ops-with-regions (nested computation as a
first-class op property) is the classical name for a realization carrying
its own routing subproblem (the mini-SabreDAG sub-router, teleport).

### 8b. The quantum instantiation (McCaskey & Nguyen, read in full 2026-06-10)

- McCaskey & Nguyen, "A MLIR Dialect for Quantum Assembly Languages,"
  IEEE QCE 2021 (arXiv:2101.11365) = the existing `mccaskey_mlir_2021` key.

What it is: a quantum dialect (QallocOp, QubitExtractOp, InstOp, Dealloc,
init/finalize) plus lowering OpenQASM -> dialect -> LLVM-dialect QIR
runtime calls -> binary, retargetable via the qcor/XACC runtime; eval =
compile time (1-2 orders faster than syntax-handler/Q# paths).

What matters for us (the gap, stated precisely, for S2.1):
1. The boundary it lowers across is the CLASSICAL-INTEGRATION boundary
   (source language -> runtime calls), not the logical-to-physical one.
   Gates are opaque named InstOps ("h", "cx" + params); no routing,
   layout, encoding, or equivalence structure exists at any level.
2. The one-to-one qubit assumption is baked in AT THE TYPE LEVEL: QIR
   deliberately leaves Qubit an opaque type ("so that implementations of
   an associated runtime library can define it in a way that best fits
   the implementation"); a qubit is a single SSA pointer extracted from
   an allocated array, indivisible by construction. This is the citable,
   type-system-level witness for our intro claim that mainstream
   toolchains assume one logical qubit = one register entry.
3. Fault tolerance appears only as a RUNTIME MODE (ftqc vs nisq command
   line flag), not as compiler representation: encoded-qubit structure is
   invisible to every IR level in this line.
4. Composes with family 8: the infrastructure and the design principles
   exist (Lattner: dialects, progressive lowering, conscious loss); the
   quantum instantiation applies them to classical integration and stops
   at an opaque qubit. LoweredOp is, in their vocabulary, a dialect op
   whose operands are rails and whose attribute is the realization set:
   expressible in their framework, absent from it. One sentence of S2.1
   says exactly this.
5. Minor: their compile-time benchmark is precedent that compile-time
   tables are accepted eval content in this space (supports E-D / S4.4).

Placement: cite in S2.1 alongside the MLIR-based quantum stacks already
cited (Catalyst, Q-MLIR); one design-principle sentence there. S4.1 gets
the mixed-level/conscious-loss sentence; S4.2 may use the
single-operation-granularity clause; S6.3's resynthesis practitioner note
can cite the raising-is-fragile argument. S1 optionally borrows the
conscious/unconscious loss vocabulary (no quote needed).

## Suggested placement in the paper

- Ch.1/Ch.2 framing sentence: "Carrying the realization set across the
  lowering boundary is delayed binding in the classical sense [BLISS-11,
  PQCC], applied to the logical-to-physical map."
- Ch.5 spine paragraph: phase-ordering + RA/IS antagonism (Bradlee quote) +
  the context-free-vs-layout-dependent tile-cost delta (family 4) = three
  sentences that position prism exactly.
- Related work: e-graphs sentence (family 5) for the IR; iterative
  compilation sentence (family 6) for the trial loop; Vegdahl MICRO-15 and
  Norris & Pollock MICRO-28 cited to anchor the lineage at the venue.

Cross-refs: conceptual_spine.md (the EDA don't-care families are the LOGIC
SYNTHESIS side of the same story; this memo is the CODE GENERATION side),
inloop_evidence.md (family 3's lesson, measured).
