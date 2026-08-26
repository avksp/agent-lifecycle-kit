# Acceptance criteria

| ID | Requirement | Evidence | Deterministic acceptance |
| --- | --- | --- | --- |
| `AC25-CONTRACT` | `R25-CONTRACT` | `EV25-CONTRACT` | Every state transition is idempotent and source-bound; parent/child lineage and per-attempt artifact namespaces cannot be replaced or crossed. |
| `AC25-LIMITS` | `R25-LIMITS` | `EV25-LIMITS` | The core performs no provider/network call; timeout or cancellation terminates the process group, terminal parents cancel every declared child, live children block parent success, cleanup is recorded and post-cancel writes fail closed. |
| `AC25-ARTIFACTS` | `R25-ARTIFACTS` | `EV25-ARTIFACTS` | Large or sensitive payloads remain outside portable lifecycle evidence. |
| `AC25-QUALIFICATION` | `R25-QUALIFICATION` | `EV25-QUALIFICATION` | A descriptor or happy path alone cannot claim support; parent-terminal child cancellation is tested, and `NO_FINAL_VERDICT`, partial child output, live child processes and stale/replayed results have no acceptance effect. |
| `AC25-INCIDENTS` | `R25-ACTIVATION` | `EV25-INCIDENTS` | WS25-02 reproduces both activated incidents with synthetic no-provider fixtures; a terminal parent cancels all declared children and cannot succeed while any child remains live, and an ordinary workflow creates neither `.alk/external-jobs` nor job state. |
| `AC25-DOCUMENTATION` | `R25-DOCUMENTATION` | `EV25-DOCUMENTATION` | Users can add a specialized tool without treating it as a model runtime or workflow controller. |
| `AC25-ACTIVATION` | `R25-ACTIVATION` | `EV25-ACTIVATION` | All incident source digests remain bound; runtime dependencies remain empty and synchronous checks stay on Release 1.88. |
