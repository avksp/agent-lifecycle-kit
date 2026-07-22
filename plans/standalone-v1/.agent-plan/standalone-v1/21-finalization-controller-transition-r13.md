# Finalization controller transition r13

Revision 13 closes the terminal goal-mode gap.

Problem:

- all workstreams could be independently accepted, but the controller stayed in
  `FINAL_AUDIT`;
- there was no durable `workflow finalize` transition to publish a final proof
  and move the run to `COMPLETE`.

Resolution:

- add a small controller-owned finalization transition;
- require `FINAL_AUDIT`, unchanged source revision and all required tasks
  accepted;
- write one canonical `agent-run-final-proof.v1` artifact;
- transition the run to `COMPLETE`;
- keep `productionPromotionClaimed: false` for the offline candidate.

Execution impact:

- accepted compatible predecessor tasks remain preservable;
- WS-14 and WS-15 must rerun so their release inventory, final audit and task
  reviews bind the finalization-capable source tree.
