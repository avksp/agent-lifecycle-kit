# Authority and artifact boundaries

Completeness accepts an explicit `operation_root` for filesystem-aware declaration checks. Without it, a PASS describes only offline structure. Task start and workflow action projection derive their operation root from the loaded workflow state through `package_root`, and check the full ownership inventory before allocating an attempt or proposing an action. Package audit applies the same check using its explicit `project_root` (or its legacy current-directory default), including legacy locks without package integrity.

Compiler output checks cover the complete packet and index footprint before creating directories. Root-bound guarded writes still enforce containment after preflight. A rootless completeness report does not authorize a filesystem operation.
