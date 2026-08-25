# Release 2.4.0

## Summary

Compose existing bug-forensics, review and evidence primitives into an optional security analysis profile with threat, exploitability, remediation and verification stages.

## Highlights

- The profile reuses existing workflow authority and remains read-only until an approved remediation task starts.
- Imported findings remain untrusted evidence until validated and linked to the current source.
- Potentially harmful execution cannot begin from an imported finding or profile alone.
- Security acceptance cannot rely only on the implementing attempt; the
  manifest policy is copied into the adopted task and enforced by the real
  task-acceptance path.

## Compatibility

The capability is optional and inactive unless a frozen plan or project profile enables it. Ordinary Release 2.0 workflows retain their behavior and cost. Release `2.4.0` has a bounded pre-implementation activation record; publication still requires a complete no-live fixture execution, independent S2 review and freeze.
