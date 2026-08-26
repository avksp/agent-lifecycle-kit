# Release 2.6.0

## Summary

Expose reviewed plan-lock, phase-resource and release-accounting builders through bounded CLI commands, and add comparable release accounting with explicit missing-data, provenance and parallel-time semantics.

## Compatibility

Existing cost and phase-resource contracts remain readable. New accounting is additive and advisory; it does not change workflow authority, infer unavailable telemetry or weaken required quality gates.

