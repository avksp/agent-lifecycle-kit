from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from release_common import file_identity, write_json


DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "`VERIFIED` for Codex CLI 0.145.0",
            "`VERIFIED` for Claude Code 2.1.220",
            "`VERIFIED` for OpenCode CLI 1.18.9",
            "`VERIFIED` for Hermes Agent v0.19.0",
            "`VERIFIED` for Qwen Code 0.21.0",
            "`EXPERIMENTAL` means",
            "bounded live host conformance",
            "usage/resource calibration",
            "Public contracts",
            "docs/reference/public-contracts.md",
        ),
    ),
    (
        "docs/ru/README.md",
        (
            "`VERIFIED` для Codex CLI 0.145.0",
            "`VERIFIED` для Claude Code 2.1.220",
            "`VERIFIED` для OpenCode CLI 1.18.9",
            "`VERIFIED` для Hermes Agent v0.19.0",
            "`VERIFIED` для Qwen Code 0.21.0",
            "`EXPERIMENTAL` означает",
            "калибровки расхода",
            "Публичных контрактах",
            "reference/public-contracts.md",
        ),
    ),
    (
        "docs/reference/public-contracts.md",
        (
            "`completionCheck`",
            "`agent-completion-check-receipt.v1`",
            "`agent-completion-gate-receipt.v1`",
            "`agent-completion-gate-validation.v1`",
            "`agent-goal-record.v1`",
            "`agent-objective-snapshot.v1`",
            "`agent-runner-state.v1`",
            "`agent-runner-snapshot.v1`",
            "`agent-managed-lifecycle-next-action.v1`",
            "`agent-managed-lifecycle-runner-receipt.v1`",
            "`agent-adapter-session-receipt.v1`",
            "`agent-managed-adapter-launch-receipt.v1`",
            "`agent-adapter-session-resume-receipt.v1`",
            "`agent-no-model-call-scan.v1`",
            "`agent-plan-completeness-profile.v1`",
            "`agent-plan-completeness-validation.v1`",
            "`agent-implementation-audit-report.v1`",
            "`agent-final-implementation-audit.v1`",
            "`agent-follow-up-register.v1`",
            "`agent-follow-up-summary.v1`",
            "`agent-worktree-isolation-policy.v1`",
            "`agent-worktree-attempt-receipt.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "`agent-adapter-event-capture-validation.v1`",
            "`agent-review-verdict.v1`",
            "`agent-review-routing-summary.v1`",
            "`agent-optional-quality-pack.v1`",
            "`agent-behavior-check-run.v1`",
            "`agent-diagnostic-bundle.v1`",
            "`agent-readonly-status-view.v1`",
            "`agent-workflow-event-feed.v1`",
            "`agent-lifecycle-progress-view.v1`",
            "`agent-lifecycle-progress-watch.v1`",
            "`agent-change-summary-receipt.v1`",
            "`agent-progress-bridge-config.v1`",
            "`agent-progress-bridge-receipt.v1`",
            "`agent-progress-hook-policy.v1`",
            "`agent-progress-hook-receipt.v1`",
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-adaptive-lifecycle-policy-request.v1`",
            "`agent-adaptive-lifecycle-policy-decision.v1`",
            "`agent-adaptive-lifecycle-policy-decision-validation.v1`",
            "`agent-small-model-task-packet.v1`",
            "`agent-small-model-output-contract.v1`",
            "`agent-small-model-output-validation.v1`",
            "`agent-small-model-packet-compile-result.v1`",
            "`agent-task-outcome-index.v1`",
            "`agent-quality-cost-signals.v1`",
            "`agent-quality-cost-signals-summary.v1`",
            "`agent-review-mesh-profile.v1`",
            "`agent-review-mesh-assignment.v1`",
            "`agent-review-mesh-result.v1`",
            "`agent-review-mesh-synthesis.v1`",
            "`agent-review-mesh-quorum-receipt.v1`",
            "`agent-review-mesh-quorum-validation.v1`",
            "`agent-failure-classification-receipt.v1`",
            "`agent-failure-classification-validation.v1`",
            "`agent-external-context-import-receipt.v1`",
            "`agent-external-context-import-validation.v1`",
            "Quality-cost learning",
            "provider/model leaderboards",
        ),
    ),
    (
        "docs/ru/reference/public-contracts.md",
        (
            "`completionCheck`",
            "`agent-completion-check-receipt.v1`",
            "`agent-completion-gate-receipt.v1`",
            "`agent-completion-gate-validation.v1`",
            "`agent-goal-record.v1`",
            "`agent-objective-snapshot.v1`",
            "`agent-runner-state.v1`",
            "`agent-runner-snapshot.v1`",
            "`agent-managed-lifecycle-next-action.v1`",
            "`agent-managed-lifecycle-runner-receipt.v1`",
            "`agent-adapter-session-receipt.v1`",
            "`agent-managed-adapter-launch-receipt.v1`",
            "`agent-adapter-session-resume-receipt.v1`",
            "`agent-no-model-call-scan.v1`",
            "`agent-plan-completeness-profile.v1`",
            "`agent-plan-completeness-validation.v1`",
            "`agent-implementation-audit-report.v1`",
            "`agent-final-implementation-audit.v1`",
            "`agent-follow-up-register.v1`",
            "`agent-follow-up-summary.v1`",
            "`agent-worktree-isolation-policy.v1`",
            "`agent-worktree-attempt-receipt.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "`agent-adapter-event-capture-validation.v1`",
            "`agent-review-verdict.v1`",
            "`agent-review-routing-summary.v1`",
            "`agent-optional-quality-pack.v1`",
            "`agent-behavior-check-run.v1`",
            "`agent-diagnostic-bundle.v1`",
            "`agent-readonly-status-view.v1`",
            "`agent-workflow-event-feed.v1`",
            "`agent-lifecycle-progress-view.v1`",
            "`agent-lifecycle-progress-watch.v1`",
            "`agent-change-summary-receipt.v1`",
            "`agent-progress-bridge-config.v1`",
            "`agent-progress-bridge-receipt.v1`",
            "`agent-progress-hook-policy.v1`",
            "`agent-progress-hook-receipt.v1`",
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-adaptive-lifecycle-policy-request.v1`",
            "`agent-adaptive-lifecycle-policy-decision.v1`",
            "`agent-adaptive-lifecycle-policy-decision-validation.v1`",
            "`agent-small-model-task-packet.v1`",
            "`agent-small-model-output-contract.v1`",
            "`agent-small-model-output-validation.v1`",
            "`agent-small-model-packet-compile-result.v1`",
            "`agent-task-outcome-index.v1`",
            "`agent-quality-cost-signals.v1`",
            "`agent-quality-cost-signals-summary.v1`",
            "`agent-review-mesh-profile.v1`",
            "`agent-review-mesh-assignment.v1`",
            "`agent-review-mesh-result.v1`",
            "`agent-review-mesh-synthesis.v1`",
            "`agent-review-mesh-quorum-receipt.v1`",
            "`agent-review-mesh-quorum-validation.v1`",
            "`agent-failure-classification-receipt.v1`",
            "`agent-failure-classification-validation.v1`",
            "`agent-external-context-import-receipt.v1`",
            "`agent-external-context-import-validation.v1`",
            "Локальная статистика качества и расхода",
            "рейтинги провайдеров",
        ),
    ),
    (
        "docs/reference/model-routing.md",
        (
            "failureSignals",
            "no-model -> local-small-packet -> standard-implementation -> stronger-review -> optional-cross-check",
            "optionalCrossCheckRecommended",
            "downgradeBlocked",
            "providerModelNamesInCore: false",
        ),
    ),
    (
        "docs/reference/quality-cost-learning.md",
        (
            "`agent-task-outcome-index.v1`",
            "`agent-quality-cost-signals.v1`",
            "`agent-lifecycle-recommendation.v1`",
            "agent-lifecycle metrics outcome-index",
            "agent-lifecycle metrics quality-signals",
            "agent-lifecycle metrics learn-recommend",
            "`autoApply: false`",
            "provider/model leaderboards",
        ),
    ),
    (
        "docs/ru/reference/quality-cost-learning.md",
        (
            "`agent-task-outcome-index.v1`",
            "`agent-quality-cost-signals.v1`",
            "`agent-lifecycle-recommendation.v1`",
            "agent-lifecycle metrics outcome-index",
            "agent-lifecycle metrics quality-signals",
            "agent-lifecycle metrics learn-recommend",
            "`autoApply: false`",
            "provider/model leaderboards",
        ),
    ),
    (
        "docs/reference/external-memory.md",
        (
            "`agent-external-context-import-receipt.v1`",
            "`sourceOfTruth: false`",
            "`rawContentStored: false`",
            "`modelCallsStarted: false`",
            "`networkCallsStarted: false`",
            "`providerApiCallsStarted: false`",
            "agent-lifecycle context external-import",
            "agent-lifecycle context episode-retrieve",
            "cannot satisfy evidence, review or final proof requirements",
        ),
    ),
    (
        "docs/ru/reference/external-memory.md",
        (
            "`agent-external-context-import-receipt.v1`",
            "`sourceOfTruth: false`",
            "`rawContentStored: false`",
            "`modelCallsStarted: false`",
            "`networkCallsStarted: false`",
            "`providerApiCallsStarted: false`",
            "agent-lifecycle context external-import",
            "agent-lifecycle context episode-retrieve",
            "не закрывает требования по доказательствам",
        ),
    ),
    (
        "docs/reference/small-model-packets.md",
        (
            "`agent-small-model-task-packet.v1`",
            "`agent-small-model-output-contract.v1`",
            "`agent-small-model-task-result.v1`",
            "`agent-small-model-output-validation.v1`",
            "agent-lifecycle task compile-small",
            "quality floor",
            "write scope",
        ),
    ),
    (
        "docs/ru/reference/small-model-packets.md",
        (
            "`agent-small-model-task-packet.v1`",
            "`agent-small-model-output-contract.v1`",
            "`agent-small-model-task-result.v1`",
            "`agent-small-model-output-validation.v1`",
            "agent-lifecycle task compile-small",
            "quality floor",
            "write scope",
        ),
    ),
    (
        "docs/reference/adaptive-lifecycle-policy.md",
        (
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-adaptive-lifecycle-policy-decision.v1`",
            "agent-lifecycle policy adaptive-decision",
            "agent-lifecycle policy adaptive-check",
            "tokens-and-resources",
            "`monetaryFieldsUsed` is always `false`",
            "quality floor",
            "quality-cost learning",
            "Failure signals",
        ),
    ),
    (
        "docs/ru/reference/adaptive-lifecycle-policy.md",
        (
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-adaptive-lifecycle-policy-decision.v1`",
            "agent-lifecycle policy adaptive-decision",
            "agent-lifecycle policy adaptive-check",
            "tokens-and-resources",
            "`monetaryFieldsUsed: false`",
            "quality floor",
        ),
    ),
    (
        "docs/reference/lifecycle-cost.md",
        (
            "agent-lifecycle metrics outcome-index",
            "agent-lifecycle metrics quality-signals",
            "agent-lifecycle metrics learn-recommend",
            "`agent-task-outcome-index.v1`",
            "`agent-quality-cost-signals.v1`",
            "does not require USD fields",
        ),
    ),
    (
        "docs/adapters/support-matrix.md",
        (
            "authoritative source-tree support claim",
            "Codex CLI 0.6.0 live evidence",
            "Claude Code 0.5.0 live evidence",
            "OpenCode Host-Local Live Evidence",
            "Hermes Host-Local Live Evidence",
            "Qwen Code Host-Local Live Evidence",
            "Cursor",
            "Gemini CLI",
            "Goose",
            "Grok Build",
            "Kimi Code",
            "OpenInterpreter",
            "Pi",
            "`adapter-event-stream`",
            "`agent-adapter-event-stream-receipt.v1`",
        ),
    ),
    (
        "docs/adapters/live-promotion-runbook.md",
        (
            "Source release",
            "Host-specific `VERIFIED`",
            "Public directory approval",
            "Production promotion",
            "validate_adapter_conformance.py",
            "validate_live_host_conformance.py",
            "validate_live_calibration.py",
            "validate_host_env_hygiene.py",
            "validate_support_matrix.py",
        ),
    ),
    (
        "docs/guides/verified-adapter-release-checklist.md",
        (
            "remote tag",
            "GitHub Release object",
            "CI status",
            "Binary assets are intentionally omitted for a source release",
            "validate_adapter_conformance.py",
            "validate_docs_compat.py",
            "validate_support_matrix.py",
        ),
    ),
    (
        "docs/reference/completion-check.md",
        (
            "`completionCheck`",
            "`agent-completion-check-receipt.v1`",
            "`agent-completion-gate-receipt.v1`",
            "agent-lifecycle specification completion-gate",
            "`agent-external-action-receipt.v1`",
            "fails closed",
        ),
    ),
    (
        "docs/reference/goal-continuity.md",
        (
            "`agent-goal-record.v1`",
            "`agent-objective-snapshot.v1`",
            "fails closed",
            "`workflow finalize`",
        ),
    ),
    (
        "docs/reference/runner.md",
        (
            "`agent-runner-policy.v1`",
            "`agent-runner-transition-request.v1`",
            "`agent-runner-snapshot.v1`",
            "fails closed",
        ),
    ),
    (
        "docs/reference/implementation-audit.md",
        (
            "`agent-implementation-audit-report.v1`",
            "`agent-final-implementation-audit.v1`",
            "agent-lifecycle audit implementation",
            "agent-lifecycle audit final-implementation",
            "`workflow task-accept`",
            "`workflow finalize`",
        ),
    ),
    (
        "docs/ru/reference/implementation-audit.md",
        (
            "`agent-implementation-audit-report.v1`",
            "`agent-final-implementation-audit.v1`",
            "agent-lifecycle audit implementation",
            "agent-lifecycle audit final-implementation",
            "`workflow task-accept`",
            "`workflow finalize`",
        ),
    ),
    (
        "docs/reference/plan-completeness.md",
        (
            "`agent-plan-completeness-profile.v1`",
            "`agent-plan-completeness-validation.v1`",
            "agent-lifecycle plan completeness-check",
            "--require-completeness",
            "missing-evidence-route",
            "missing-budget-policy",
        ),
    ),
    (
        "docs/ru/reference/plan-completeness.md",
        (
            "`agent-plan-completeness-profile.v1`",
            "`agent-plan-completeness-validation.v1`",
            "agent-lifecycle plan completeness-check",
            "--require-completeness",
            "missing-evidence-route",
            "missing-budget-policy",
        ),
    ),
    (
        "docs/reference/follow-up-register.md",
        (
            "`agent-follow-up-register.v1`",
            "`agent-follow-up-summary.v1`",
            "fails closed",
            "`workflow finalize`",
        ),
    ),
    (
        "docs/reference/worktree-isolation.md",
        (
            "`agent-worktree-isolation-policy.v1`",
            "`agent-worktree-attempt-receipt.v1`",
            "preserved unless",
            "`runner transition`",
        ),
    ),
    (
        "docs/reference/adapter-event-capture.md",
        (
            "`adapter-event-stream`",
            "`agent-adapter-event.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "`agent-adapter-event-capture-validation.v1`",
            "`adapter-owned`",
            "No automatic hook installation",
            "Adapter event capture matrix",
            "fails closed",
        ),
    ),
    (
        "docs/ru/reference/adapter-event-capture.md",
        (
            "`adapter-event-stream`",
            "`agent-adapter-event.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "`adapter-owned`",
            "Автоматическая установка: нет",
            "матрице захвата событий адаптеров",
        ),
    ),
    (
        "docs/adapters/event-capture-matrix.md",
        (
            "`agent-adapter-event.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "No automatic hook installation",
            "`adapter-owned`",
            "conformance/adapters/codex/event-stream-receipt.json",
            "conformance/adapters/qwen-code/event-stream-receipt.json",
        ),
    ),
    (
        "docs/ru/adapters/event-capture-matrix.md",
        (
            "`agent-adapter-event.v1`",
            "`agent-adapter-event-stream-receipt.v1`",
            "Автоматическая установка: нет",
            "`adapter-owned`",
            "conformance/adapters/codex/event-stream-receipt.json",
            "conformance/adapters/qwen-code/event-stream-receipt.json",
        ),
    ),
    (
        "docs/reference/review-verdict.md",
        (
            "`agent-review-verdict.v1`",
            "`agent-review-verdict-validation.v1`",
            "`agent-review-routing-summary.v1`",
            "fails closed",
            "agent-lifecycle audit review-check",
        ),
    ),
    (
        "docs/reference/optional-quality-packs.md",
        (
            "`agent-optional-quality-pack.v1`",
            "`agent-optional-quality-pack-validation.v1`",
            "`agent-behavior-check-fixture.v1`",
            "`agent-behavior-check-run.v1`",
            "resource caps",
            "agent-lifecycle quality pack-check",
            "agent-lifecycle quality behavior-check",
        ),
    ),
    (
        "docs/reference/diagnostic-bundles.md",
        (
            "`agent-diagnostic-bundle.v1`",
            "redacted",
            "source of truth",
            "artifact count",
            "agent-lifecycle diagnostics bundle",
        ),
    ),
    (
        "docs/reference/read-only-status-view.md",
        (
            "`agent-readonly-status-view.v1`",
            "`agent-workflow-event-feed.v1`",
            "`agent-lifecycle-progress-view.v1`",
            "`agent-lifecycle-progress-watch.v1`",
            "`agent-change-summary-receipt.v1`",
            "`agent-progress-bridge-receipt.v1`",
            "not source of truth",
            "small local model",
            "agent-lifecycle report status-view",
            "agent-lifecycle report event-feed",
            "agent-lifecycle report progress",
            "agent-lifecycle report progress-bridge",
            "agent-lifecycle report change-summary",
            "--watch",
            "--terminal",
            "host-specific telemetry",
        ),
    ),
    (
        "docs/ru/reference/read-only-status-view.md",
        (
            "`agent-readonly-status-view.v1`",
            "`agent-workflow-event-feed.v1`",
            "`agent-lifecycle-progress-view.v1`",
            "`agent-lifecycle-progress-watch.v1`",
            "`agent-change-summary-receipt.v1`",
            "`agent-progress-bridge-receipt.v1`",
            "не является источником правды",
            "agent-lifecycle report progress-bridge",
            "--watch",
            "--terminal",
            "телеметрию конкретного хоста",
        ),
    ),
    (
        "docs/reference/cli.md",
        (
            "import plan --source <file-or-folder>",
            "openspec|spec-kit|bmad|spec-kitty",
            "docs/guides/lifecycle-cookbook.md",
            "adapter session start/status/resume/promote",
            "adapter run",
            "`WAITING_FOR_TASK`",
            "`agent-adapter-session-receipt.v1`",
        ),
    ),
    (
        "docs/ru/reference/cli.md",
        (
            "import plan/check",
            "openspec|spec-kit|bmad|spec-kitty",
            "docs/ru/lifecycle-cookbook.md",
            "adapter session start/status/resume/promote",
            "adapter run",
            "`WAITING_FOR_TASK`",
            "`agent-adapter-session-receipt.v1`",
        ),
    ),
    (
        "docs/guides/lifecycle-cookbook.md",
        (
            "Research and planning only",
            "Review a Markdown plan folder",
            "Review code changes",
            "Audit implementation evidence",
            "Coordinate cross-review",
            "agent-lifecycle adapter task start",
            "agent-lifecycle import plan",
            "review-mesh recommend",
        ),
    ),
    (
        "docs/ru/lifecycle-cookbook.md",
        (
            "Исследование и планирование",
            "Проверка папки с Markdown-планом",
            "Проверка изменений кода",
            "Аудит подтверждений реализации",
            "Согласованная перепроверка",
            "agent-lifecycle adapter task start",
            "agent-lifecycle import plan",
            "review-mesh recommend",
        ),
    ),
    (
        "docs/reference/import-mappers.md",
        (
            "`openspec-planning`",
            "`github-spec-kit-planning`",
            "`bmad-method-planning`",
            "`spec-kitty-planning`",
            "agent-markdown-source-collection.v1",
            "--dialect openspec",
            "--dialect spec-kit",
        ),
    ),
    (
        "docs/ru/reference/import-mappers.md",
        (
            "`openspec-planning`",
            "`github-spec-kit-planning`",
            "`bmad-method-planning`",
            "`spec-kitty-planning`",
            "agent-markdown-source-collection.v1",
            "--dialect openspec",
            "--dialect spec-kit",
        ),
    ),
    (
        "docs/adapters/install.md",
        (
            "`agent-lifecycle adapter session start/status/resume/promote`",
            "`agent-lifecycle adapter run`",
            "`agent-adapter-session-receipt.v1`",
            "`managedLaunch.status: WRAPPER_ONLY`",
            "docs/adapters/managed-session-support.md",
        ),
    ),
    (
        "docs/ru/adapters/install.md",
        (
            "`agent-lifecycle adapter session start/status/resume/promote`",
            "`agent-lifecycle adapter run`",
            "`agent-adapter-session-receipt.v1`",
            "`managedLaunch.status: WRAPPER_ONLY`",
            "docs/ru/adapters/managed-session-support.md",
        ),
    ),
    (
        "docs/reference/automatic-progress-bridge.md",
        (
            "`agent-progress-bridge-receipt.v1`",
            "`agent-progress-bridge-config.v1`",
            "readOnly: true",
            "modelCallsStarted: false",
            "tokenSpendForProgress: false",
            "hostTelemetryParsedInCore: false",
            "agent-lifecycle report progress-bridge",
            "does not infer missing counts",
            "Host adapters remain responsible",
        ),
    ),
    (
        "docs/ru/reference/automatic-progress-bridge.md",
        (
            "`agent-progress-bridge-receipt.v1`",
            "`agent-progress-bridge-config.v1`",
            "readOnly: true",
            "modelCallsStarted: false",
            "tokenSpendForProgress: false",
            "hostTelemetryParsedInCore: false",
            "agent-lifecycle report progress-bridge",
            "не вычисляет токены",
            "Адаптеры хостов отвечают",
        ),
    ),
    (
        "docs/reference/managed-adapter-sessions.md",
        (
            "`agent-adapter-session-receipt.v1`",
            "`agent-managed-adapter-launch-receipt.v1`",
            "`agent-adapter-session-resume-receipt.v1`",
            "adapter session start",
            "adapter session resume",
            "adapter run",
            "`WRAPPER_ONLY`",
            "shell: false",
            "adapter-generic-launch-disabled",
            "wildcard",
            "plugin installation alone",
        ),
    ),
    (
        "docs/reference/readiness-diagnostics.md",
        (
            "`agent-adapter-install-plan.v1`",
            "schema-validated installation facts",
            "argv arrays",
            "Diagnostics never interpret the argv",
            "arrays as a shell command",
        ),
    ),
    (
        "docs/security/neutrality-contract.md",
        (
            "Completeness counters",
            "`readRaces`",
            "`pathAliasConflicts`",
            "fail closed",
        ),
    ),
    (
        "docs/reference/project-comparison.md",
        (
            "lifecycle controller",
            "not a runtime",
            "not a model broker",
            "Source of truth remains the frozen ALK plan",
        ),
    ),
    (
        "docs/ru/reference/project-comparison.md",
        (
            "не кодовый агент",
            "не платформа запуска моделей",
            "Источником правды остаётся зафиксированный план ALK",
        ),
    ),
    (
        "docs/ru/reference/managed-adapter-sessions.md",
        (
            "`agent-adapter-session-receipt.v1`",
            "`agent-managed-adapter-launch-receipt.v1`",
            "`agent-adapter-session-resume-receipt.v1`",
            "adapter session start",
            "adapter session resume",
            "adapter run",
            "`WRAPPER_ONLY`",
            "shell: false",
            "adapter-generic-launch-disabled",
            "шаблоны",
            "установка плагина",
        ),
    ),
    (
        "docs/ru/reference/readiness-diagnostics.md",
        (
            "`agent-adapter-install-plan.v1`",
            "argv-массивы",
            "не трактует argv-массивы как строку shell",
        ),
    ),
    (
        "docs/ru/security/neutrality-contract.md",
        (
            "Счётчики полноты",
            "`readRaces`",
            "`pathAliasConflicts`",
            "приводит к отказу",
        ),
    ),
    (
        "docs/reference/review-mesh.md",
        (
            "`agent-review-mesh-profile.v1`",
            "`agent-review-mesh-assignment.v1`",
            "`agent-review-mesh-result.v1`",
            "`agent-review-mesh-synthesis.v1`",
            "`agent-review-mesh-quorum-receipt.v1`",
            "`agent-review-mesh-quorum-validation.v1`",
            "`agent-review-mesh-prepare-receipt.v1`",
            "leader-draft-multi-review",
            "parallel-research-synthesis",
            "implementation-audit-panel",
            "review-mesh prepare",
            "not part of the default lifecycle",
            "does not recommend",
            "launch adapters",
            "tokens, invocation count and wall-clock resources",
            "hostIdentityHash",
            "modelIdentityHash",
        ),
    ),
    (
        "docs/ru/reference/review-mesh.md",
        (
            "`agent-review-mesh-profile.v1`",
            "`agent-review-mesh-assignment.v1`",
            "`agent-review-mesh-result.v1`",
            "`agent-review-mesh-synthesis.v1`",
            "`agent-review-mesh-quorum-receipt.v1`",
            "`agent-review-mesh-quorum-validation.v1`",
            "`agent-review-mesh-prepare-receipt.v1`",
            "leader-draft-multi-review",
            "parallel-research-synthesis",
            "implementation-audit-panel",
            "review-mesh prepare",
            "базовый жизненный цикл",
            "не запускает адаптеры",
            "токенами, числом вызовов и временем выполнения",
            "hostIdentityHash",
            "modelIdentityHash",
        ),
    ),
    (
        "docs/adapters/progress-bridge-matrix.md",
        (
            "Progress support is documented separately from adapter maturity",
            "`AUTO`",
            "`WATCH`",
            "`MANUAL`",
            "`UNSUPPORTED`",
            "agent-lifecycle report progress-bridge",
            "No adapter claims unsupported native hooks",
        ),
    ),
    (
        "docs/adapters/managed-session-support.md",
        (
            "Managed session support is separate from adapter maturity",
            "`WRAPPER_ONLY`",
            "agent-lifecycle adapter run",
            "does not claim safe native argv launch",
            "plugin installation",
        ),
    ),
    (
        "docs/ru/adapters/managed-session-support.md",
        (
            "Поддержка управляемых сессий отделена от зрелости адаптера",
            "`WRAPPER_ONLY`",
            "agent-lifecycle adapter run",
            "не заявляет безопасный прямой запуск CLI",
            "подтверждением жизненного цикла",
        ),
    ),
    (
        "docs/ru/adapters/progress-bridge-matrix.md",
        (
            "Поддержка прогресса описывается отдельно от зрелости адаптера",
            "`AUTO`",
            "`WATCH`",
            "`MANUAL`",
            "`UNSUPPORTED`",
            "agent-lifecycle report progress-bridge",
            "не заявляет неподтверждённые прямые",
        ),
    ),
    (
        "release/notes/v0.19.0.md",
        (
            "Status: source release.",
            "Updated package metadata to `0.19.0`",
            "`agent-optional-quality-pack.v1`",
            "`agent-behavior-check-run.v1`",
            "`agent-diagnostic-bundle.v1`",
            "`agent-readonly-status-view.v1`",
            "`agent-lifecycle quality pack-check`",
            "`agent-lifecycle diagnostics bundle`",
            "`agent-lifecycle report status-view`",
            "productionPromotionClaimed",
        ),
    ),
)

OPTIONAL_DOC_RULE_PATHS = {
    "docs/reference/review-mesh.md",
    "docs/ru/reference/review-mesh.md",
}

ADAPTER_DOCS = (
    "docs/adapters/claude.md",
    "docs/adapters/codex.md",
    "docs/adapters/cursor.md",
    "docs/adapters/gemini-cli.md",
    "docs/adapters/goose.md",
    "docs/adapters/grok-build.md",
    "docs/adapters/hermes.md",
    "docs/adapters/kimi-code.md",
    "docs/adapters/opencode.md",
    "docs/adapters/openinterpreter.md",
    "docs/adapters/pi.md",
    "docs/adapters/qwen-code.md",
)

VERIFIED_ROW = re.compile(r"^\|[^|\n]+\|[^|\n]+\|\s*VERIFIED\s*\|", re.MULTILINE)
PRODUCTION_READY_CLAIM = re.compile(r"\b(production[- ]ready|production ready)\b", re.IGNORECASE)
VERSIONED_FEATURE_PROSE = re.compile(
    r"(?i)(?:release\s+0\.\d+\s+(?:adds?|defines?|introduces?|implements?|ships?|also\s+accepts)|"
    r"0\.\d+\s+line\s+adds|^#{2,}\s+0\.\d+\s+)",
    re.MULTILINE,
)
LEGACY_VERIFIED_DOC_HOSTS = {"Codex", "Claude Code", "OpenCode", "Hermes", "Qwen Code"}
REQUIRED_VERIFIED_EVIDENCE_KINDS = {
    "live-host-conformance",
    "live-usage-calibration",
    "lifecycle-final-proof",
}
HOST_DISPLAY_NAMES = {
    "claude": "Claude Code",
    "claude-code": "Claude Code",
    "codex": "Codex",
    "cursor": "Cursor",
    "gemini-cli": "Gemini CLI",
    "goose": "Goose",
    "grok-build": "Grok Build",
    "hermes": "Hermes",
    "kimi-code": "Kimi Code",
    "opencode": "OpenCode",
    "openinterpreter": "OpenInterpreter",
    "pi": "Pi",
    "qwen-code": "Qwen Code",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    verified_doc_hosts = LEGACY_VERIFIED_DOC_HOSTS | _verified_doc_hosts_from_evidence_index(root, blockers)

    review_mesh_docs_available = (root / "docs/reference/review-mesh.md").is_file()
    for relative, required in DOC_RULES:
        if relative in OPTIONAL_DOC_RULE_PATHS and not (root / relative).is_file():
            checks.append({"path": relative, "status": "SKIPPED", "required": list(required), "identity": None})
            continue
        if relative in {"docs/reference/public-contracts.md", "docs/ru/reference/public-contracts.md"} and not review_mesh_docs_available:
            required = tuple(item for item in required if "agent-review-mesh" not in item)
        checks.append(_check_doc(root, relative, required, blockers, verified_doc_hosts))
    for relative in ADAPTER_DOCS:
        checks.append(_check_adapter_doc(root, relative, blockers, verified_doc_hosts))
    checks.append(_check_versioned_feature_prose(root, blockers))

    evidence = {
        "schemaVersion": "agent-docs-compat-evidence.v1",
        "status": "PASS" if not blockers else "FAIL",
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _check_doc(
    root: Path,
    relative: str,
    required: tuple[str, ...],
    blockers: list[dict[str, Any]],
    verified_doc_hosts: set[str],
) -> dict[str, Any]:
    path = root / relative
    check: dict[str, Any] = {"path": relative, "status": "PASS", "required": list(required), "identity": None}
    if not path.is_file():
        blockers.append({"code": "docs-compat-file-missing", "message": f"{relative} is missing"})
        check["status"] = "FAIL"
        return check
    text = path.read_text(encoding="utf-8")
    check["identity"] = file_identity(path)
    missing = [phrase for phrase in required if phrase not in text]
    if missing:
        blockers.append({"code": "docs-compat-required-text-missing", "message": f"{relative} missing: {', '.join(missing)}"})
        check["status"] = "FAIL"
    if _contains_overclaim(relative, text, blockers, verified_doc_hosts):
        check["status"] = "FAIL"
    return check


def _check_adapter_doc(root: Path, relative: str, blockers: list[dict[str, Any]], verified_doc_hosts: set[str]) -> dict[str, Any]:
    path = root / relative
    if relative == "docs/adapters/claude.md":
        required = ("`VERIFIED`", "Claude Code 2.1.220", "live conformance", "does not claim official")
    elif relative == "docs/adapters/codex.md":
        required = ("`VERIFIED`", "Codex CLI 0.145.0", "live conformance", "does not claim public")
    elif relative == "docs/adapters/goose.md":
        required = ("`VERIFIED`", "Goose `1.45.0`", "live conformance", "does not claim public")
    elif relative == "docs/adapters/grok-build.md" and "Grok Build" in verified_doc_hosts:
        required = ("`VERIFIED`", "Grok Build `0.2.117`", "live conformance", "does not claim public")
    elif relative == "docs/adapters/grok-build.md":
        required = ("`EXPERIMENTAL`", "probe", "conformance")
    elif relative == "docs/adapters/opencode.md":
        required = ("`VERIFIED`", "OpenCode CLI `1.18.9`", "live conformance", "does not claim npm")
    elif relative == "docs/adapters/hermes.md":
        required = ("`VERIFIED`", "Hermes Agent `v0.19.0`", "live conformance", "does not claim public")
    elif relative == "docs/adapters/qwen-code.md":
        required = ("`VERIFIED`", "Qwen Code `0.21.0`", "live conformance", "does not claim public")
    elif relative == "docs/adapters/openinterpreter.md" and "OpenInterpreter" in verified_doc_hosts:
        required = ("`VERIFIED`", "`interpreter` 0.0.34", "live conformance", "does not claim public")
    elif relative == "docs/adapters/pi.md" and "Pi" in verified_doc_hosts:
        required = ("`VERIFIED`", "Pi `0.83.0`", "live conformance", "does not claim public")
    else:
        required = ("`EXPERIMENTAL`", "live", "conformance")
    check = _check_doc(root, relative, required, blockers, verified_doc_hosts)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if (
            "`VERIFIED`" in text
            and relative
            not in {
                "docs/adapters/claude.md",
                "docs/adapters/codex.md",
                "docs/adapters/goose.md",
                "docs/adapters/grok-build.md",
                "docs/adapters/opencode.md",
                "docs/adapters/hermes.md",
                "docs/adapters/qwen-code.md",
                "docs/adapters/openinterpreter.md",
                "docs/adapters/pi.md",
            }
            and "until live" not in text
            and "not `VERIFIED`" not in text
        ):
            blockers.append({"code": "docs-compat-adapter-verified-overclaim", "message": f"{relative} mentions VERIFIED without live-evidence qualifier"})
            check["status"] = "FAIL"
    return check


def _contains_overclaim(relative: str, text: str, blockers: list[dict[str, Any]], verified_doc_hosts: set[str]) -> bool:
    failed = False
    invalid_verified_rows = [
        row
        for row in VERIFIED_ROW.findall(text)
        if _verified_row_host(row) not in verified_doc_hosts
    ]
    if invalid_verified_rows:
        blockers.append({"code": "docs-compat-verified-row", "message": f"{relative} contains a VERIFIED current-maturity row"})
        failed = True
    if "offline source release" in text.lower() and PRODUCTION_READY_CLAIM.search(text):
        blockers.append({"code": "docs-compat-production-ready-overclaim", "message": f"{relative} overclaims offline source release readiness"})
        failed = True
    return failed


def _check_versioned_feature_prose(root: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    checked: list[str] = []
    matches: list[dict[str, Any]] = []
    paths = [root / "README.md"]
    docs_root = root / "docs"
    if docs_root.is_dir():
        paths.extend(sorted(docs_root.rglob("*.md")))
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("docs/adapters/evidence/"):
            continue
        checked.append(relative)
        text = path.read_text(encoding="utf-8")
        for match in VERSIONED_FEATURE_PROSE.finditer(text):
            matches.append({"path": relative, "text": match.group(0).strip()})
    check: dict[str, Any] = {"path": "ordinary-docs", "status": "PASS", "checked": checked}
    if matches:
        blockers.append(
            {
                "code": "docs-compat-versioned-feature-prose",
                "message": "ordinary docs must describe behavior without release-version introduction prose",
                "matches": matches,
            }
        )
        check["status"] = "FAIL"
    return check


def _verified_row_host(row: str) -> str:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    return cells[0] if cells else ""


def _verified_doc_hosts_from_evidence_index(root: Path, blockers: list[dict[str, Any]]) -> set[str]:
    index_path = root / "docs/adapters/evidence/adapter-evidence-summary.v1.json"
    if not index_path.is_file():
        return set()
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blockers.append(
            {
                "code": "docs-compat-evidence-index-invalid-json",
                "message": f"{index_path.relative_to(root).as_posix()} is invalid JSON: {exc.msg}",
            }
        )
        return set()

    verified_hosts: set[str] = set()
    for item in index.get("adapters", []):
        if not _has_verified_live_evidence(root, item):
            continue
        for key in ("adapterId", "host"):
            value = item.get(key)
            if isinstance(value, str):
                verified_hosts.add(_host_display_name(value))
        descriptor = _read_descriptor(root, item.get("adapterId"))
        for key in ("adapterId", "host"):
            value = descriptor.get(key)
            if isinstance(value, str):
                verified_hosts.add(_host_display_name(value))
    return verified_hosts


def _has_verified_live_evidence(root: Path, item: dict[str, Any]) -> bool:
    if item.get("maturity") != "VERIFIED":
        return False
    if item.get("productionPromotionClaimed") or item.get("publicDirectoryApprovalClaimed"):
        return False
    if not item.get("testedHostRange"):
        return False
    evidence_kinds = set(item.get("evidenceKinds", []))
    if not REQUIRED_VERIFIED_EVIDENCE_KINDS.issubset(evidence_kinds):
        return False
    summary_path = item.get("summaryPath")
    return isinstance(summary_path, str) and (root / summary_path).is_file()


def _read_descriptor(root: Path, adapter_id: Any) -> dict[str, Any]:
    if not isinstance(adapter_id, str):
        return {}
    descriptor_path = root / "adapters" / adapter_id / "adapter.descriptor.json"
    if not descriptor_path.is_file():
        return {}
    try:
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return descriptor if isinstance(descriptor, dict) else {}


def _host_display_name(value: str) -> str:
    return HOST_DISPLAY_NAMES.get(value, value.replace("-", " ").title())


if __name__ == "__main__":
    raise SystemExit(main())
