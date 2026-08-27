# Release 2.7.0

## Summary

Add review-round escalation, safe finding-check disposition, statistical evidence provenance and quality-preserving audit efficiency metrics. Correct the existing omission that allowed open `CRITICAL` findings through review, implementation-audit, completion, finalization and plan-package acceptance gates.

Audit-efficiency comparisons reject repeated `releaseId`, `sourceRevision`, `sourceLineageDigest` or label-independent content identities before counting samples or publishing measured reduction percentages.

## Compatibility

Existing findings and audit samples remain readable. Findings-only Review Mesh imports remain advisory. New statistical confidence claims require explicit provenance, current lineage, unique sample identity and adequacy. No reviewer text is executable and no budget limit or reviewer agreement can waive an open required finding.
