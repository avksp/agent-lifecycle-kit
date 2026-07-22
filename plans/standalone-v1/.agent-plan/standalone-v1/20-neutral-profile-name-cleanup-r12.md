# Neutral profile key cleanup r12

Revision 12 is a hygiene-only refreeze.

Change:

- rename the neutrality archive-policy key from a project-looking term to
  `rejectAbsoluteTraversalAdsDeviceOrTrailingSpaceDotPaths`.

Reason:

- the standalone repository must not contain source-project names or
  project-looking artifacts;
- the key still expresses the same generic path-safety rule: reject absolute
  paths, traversal, device paths and trailing space/dot path forms.

Scope:

- no requirement, workstream, validation command, adapter, evidence or release
  behavior changes;
- prior accepted compatible tasks remain preservable.
