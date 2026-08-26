# Release 2.6 observed baseline

This bounded baseline is the input to Release 2.7 audit-efficiency metrics. It
does not set a reduction target and cannot promote an optimization profile.

- accepted release: `v2.6.0`, merge `30e2f2a55a2b8d959fa22b884e122952a2711ff7`;
- workflow run: `release-2-6-run-1`, source revision
  `b676b2db77c862a7df4be3373023ef315a88cd25`;
- local accounting digest:
  `b34cffec93d2841af52cfab8dd3651017aa1b3569d6a63271959c24bff497024`;
- total elapsed wall window: `21,147,274 ms` (`MIXED`);
- ALK process wall window: `4,679,707 ms` (`TIME_WINDOW_ONLY`);
- implementation wall window: `4,510,000 ms` (`TIME_WINDOW_ONLY`);
- independent audit: `29,195,208` measured tokens, `9,278,567 ms`
  measured wall, `12,228,901 ms` measured compute, `22` measured sessions;
- post-audit remediation wall window: `2,679,000 ms`
  (`TIME_WINDOW_ONLY`);
- ALK process, implementation and remediation token telemetry:
  `UNAVAILABLE`, never zero.

The accounting window starts at the earliest independent S2 session and ends
when the GitHub Release was published. Audit wall time is the union of auditor
session intervals; audit compute time sums parallel sessions. Implementation
and remediation values are workflow-event windows. ALK process time is the
non-overlapping residual, including planning, lifecycle commands, CI, merge and
GitHub Release ceremony.

Release 2.7 must reproduce this shape in a portable tracked fixture and prove
metric semantics. One release is insufficient to claim a safe percentage
reduction. Any later optimization target requires another comparable release
and must preserve all security, architecture, quality and review floors.
