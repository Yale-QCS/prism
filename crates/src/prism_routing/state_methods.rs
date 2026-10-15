// PRISM-specific `RoutingState` methods, textually included into
// `sabre/route.rs` via `include!` so they share the file's imports and have
// direct access to private fields without forcing any `pub`/`pub(super)`
// markers onto the vendored struct.

impl<'a> RoutingState<'a> {
    /// Commit a `MultiTwoQ` node atomically (returning the kind) or defer it
    /// into the front layer (returning `None`, signalling the caller to
    /// `continue`). Delegates to `RealizationFrontLayer::commit_or_defer_multi`.
    fn commit_or_defer_multi(
        &mut self,
        node_id: NodeIndex,
        realizations: &ext::VirtRealizations,
        default_realization: u32,
    ) -> Option<RoutedItemKind> {
        let r_idx = self.front_layer.commit_or_defer_multi(
            node_id,
            realizations,
            default_realization,
            &self.layout,
            &self.target.distance.view(),
        )?;
        Some(RoutedItemKind::MultiTwoQ(r_idx))
    }

    /// Push a `MultiTwoQ` successor's realizations into the extended set,
    /// if the successor is a `MultiTwoQ` node. No-op otherwise. Called right
    /// after `populate_extended_set`'s stock `if let InteractionKind::TwoQ`.
    fn maybe_push_multi_extended(&mut self, successor_node: NodeIndex) {
        if let InteractionKind::MultiTwoQ { realizations, .. } = &self.sabre.dag[successor_node].kind
        {
            let phys = ext::materialize_phys_reals(realizations, &self.layout);
            self.extended_set.push_multi(phys);
        }
    }

    /// Push any multi-rep node touching either endpoint of `swap` whose
    /// chosen realization is fully adjacent, then dedupe. Called after each
    /// best-swap in the main routing loop.
    fn collect_multi_routable_after_swap(
        &self,
        swap: [PhysicalQubit; 2],
        out: &mut Vec<NodeIndex>,
    ) {
        for &qubit in &swap {
            for &node in self.front_layer.multi_nodes_on(qubit).iter() {
                if let Some(reals) = self.front_layer.multi_get(&node) {
                    let adjacent = |real: &Box<[[PhysicalQubit; 2]]>| {
                        real.iter()
                            .all(|p| self.target.neighbors.contains_edge(p[0], p[1]))
                    };
                    if reals.iter().any(adjacent) {
                        out.push(node);
                    }
                }
            }
        }
        out.sort_unstable();
        out.dedup();
    }

    /// Drop-in for `force_enable_closest_node`: if a multi-rep realization
    /// is strictly closer than the closest stock node, sub-route it (commit
    /// happens internally) and return an empty list; otherwise delegate to
    /// `force_enable_closest_node` and return its routable seed. The empty
    /// return signals the caller to skip the usual remove + `update_route`.
    fn force_enable_or_subroute(
        &mut self,
        current_swaps: &mut Vec<[PhysicalQubit; 2]>,
    ) -> SmallVec<[NodeIndex; 2]> {
        if let Some((node, real_idx)) = ext::pick_multi_force_target(
            &self.front_layer,
            &self.target.distance.view(),
        ) {
            debug_assert!(current_swaps.is_empty());
            let schedule = self.sub_route_realization(node, real_idx);
            self.commit_sub_routed_node(node, real_idx as u32, schedule);
            return SmallVec::new();
        }
        self.force_enable_closest_node(current_swaps)
    }

    /// Sub-route a multi-rep node's chosen realization via a recursive
    /// `swap_map_trial` on a mini-`SabreDAG`. Mini's decisions are applied
    /// to outer state; `phys_load` is bumped per sub-gate fire.
    fn sub_route_realization(
        &mut self,
        target_node: NodeIndex,
        real_idx: usize,
    ) -> Box<[SubGate]> {
        let virt_real: Box<[[VirtualQubit; 2]]> = match &self.sabre.dag[target_node].kind {
            InteractionKind::MultiTwoQ { realizations, .. } => realizations[real_idx].clone(),
            _ => panic!("sub_route_realization called on non-MultiTwoQ node"),
        };
        let mini_sabre = ext::build_mini_sabredag(&virt_real);
        let mini_problem = RoutingProblem {
            sabre: &mini_sabre,
            ..self.problem()
        };
        let mini_result = swap_map_trial(mini_problem, &self.layout, self.seed.wrapping_add(1));
        let mut schedule: Vec<SubGate> = Vec::with_capacity(mini_result.order.len());
        for item in &mini_result.order {
            for &swap in item.initial_swaps() {
                self.apply_swap(swap);
            }
            let sub_idx = mini_sabre.dag[item.node].indices[0].index();
            let virt_pair = virt_real[sub_idx];
            let p0 = virt_pair[0].to_phys(&self.layout);
            let p1 = virt_pair[1].to_phys(&self.layout);
            self.front_layer.bump_pair_load(p0, p1);
            schedule.push(SubGate {
                sub_idx: sub_idx as u32,
                swaps_before: item.initial_swaps().to_vec().into_boxed_slice(),
            });
        }
        schedule.into_boxed_slice()
    }

    /// Record a sub-routed `MultiTwoQ` commit and advance its successors.
    fn commit_sub_routed_node(
        &mut self,
        node: NodeIndex,
        real_idx: u32,
        schedule: Box<[SubGate]>,
    ) {
        self.front_layer.remove(&node);
        self.order.push(RoutedItem {
            initial_swaps: None,
            node,
            kind: RoutedItemKind::SubRoutedMultiTwoQ { real_idx, schedule },
        });
        let successors: Vec<NodeIndex> = self
            .sabre
            .dag
            .edges_directed(node, Direction::Outgoing)
            .map(|e| e.target())
            .collect();
        let mut next_routable = Vec::new();
        for s in successors {
            let idx = s.index();
            self.required_predecessors[idx] -= 1;
            if self.required_predecessors[idx] == 0 {
                next_routable.push(s);
            }
        }
        self.update_route(&next_routable, None)
    }
}

/// Flatten a stock `RoutingResult` into prism's flat event stream.
/// Lives in the route module so it can read the private fields/variants of
/// `RoutingResult`, `RoutedItem`, and `RoutedItemKind` without requiring
/// any `pub` markers on the vendored struct.
pub fn flatten_routing_result(
    result: &RoutingResult<'_>,
    n_phys: u32,
) -> (Vec<(u8, u32, u32)>, Vec<u32>, u32) {
    use crate::prism_routing::input::{EVENT_KIND_COMMIT, EVENT_KIND_SUB_GATE, EVENT_KIND_SWAP};
    let mut events: Vec<(u8, u32, u32)> = Vec::with_capacity(result.order.len() * 2);
    let mut n_swaps: u32 = 0;
    for item in &result.order {
        for swap in item.initial_swaps() {
            events.push((EVENT_KIND_SWAP, swap[0].0, swap[1].0));
            n_swaps += 1;
        }
        let op_idx = result.sabre.dag[item.node].indices[0].index() as u32;
        match &item.kind {
            RoutedItemKind::Simple => events.push((EVENT_KIND_COMMIT, op_idx, 0)),
            RoutedItemKind::MultiTwoQ(r_idx) => {
                events.push((EVENT_KIND_COMMIT, op_idx, *r_idx))
            }
            RoutedItemKind::SubRoutedMultiTwoQ { real_idx, schedule } => {
                // Sub-routed commit: pack `(real_idx << 16) | sub_idx` into
                // the third field of SUB_GATE events.
                for sg in schedule.iter() {
                    for swap in sg.swaps_before.iter() {
                        events.push((EVENT_KIND_SWAP, swap[0].0, swap[1].0));
                        n_swaps += 1;
                    }
                    let packed = (*real_idx << 16) | (sg.sub_idx & 0xFFFF);
                    events.push((EVENT_KIND_SUB_GATE, op_idx, packed));
                }
            }
            RoutedItemKind::ControlFlow(_) => {
                unreachable!("prism IR never produces ControlFlow nodes")
            }
        }
    }
    n_swaps += result.final_swaps.len() as u32;
    let final_v2p: Vec<u32> = (0..n_phys)
        .map(|v| VirtualQubit::new(v).to_phys(&result.final_layout).0)
        .collect();
    (events, final_v2p, n_swaps)
}
