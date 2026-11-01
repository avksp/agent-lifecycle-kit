from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from docs_compat_rules import DOC_RULES_REMAINDER
from release_common import file_identity, write_json

# Maintained manuals only; historical receipts and release evidence are not manuals.
# Alternatives name actual supported locations, not a recursive filename heuristic.
MANUAL_PAIRS = (
    ("docs/architecture/modular-controller.md", ("docs/ru/architecture/modular-controller.md",)),
    ("docs/architecture/release-architecture.md", ("docs/ru/architecture/release-architecture.md",)),
    ("docs/architecture/runner-extension-map.md", ("docs/ru/architecture/runner-extension-map.md",)),
    ("docs/architecture/runner-transition-contract.md", ("docs/ru/architecture/runner-transition-contract.md",)),
    ("docs/architecture/system-architecture.md", ("docs/ru/architecture/system-architecture.md",)),
    ("docs/guides/budget-reroute-policy.md", ("docs/ru/guides/budget-reroute-policy.md",)),
    (
        "docs/guides/code-review-workflows.md",
        ("docs/ru/guides/code-review-workflows.md", "docs/ru/code-review-workflows.md"),
    ),
    ("docs/guides/controlled-technical-english.md", ("docs/ru/guides/controlled-technical-english.md",)),
    ("docs/guides/how-alk-works.md", ("docs/ru/guides/how-alk-works.md",)),
    ("docs/guides/lifecycle-cookbook.md", ("docs/ru/guides/lifecycle-cookbook.md", "docs/ru/lifecycle-cookbook.md")),
    ("docs/guides/verified-adapter-release-checklist.md", ("docs/ru/guides/verified-adapter-release-checklist.md",)),
    ("docs/operations/retention-maintenance.md", ("docs/ru/operations/retention-maintenance.md",)),
    ("docs/reference/lifecycle-cost.md", ("docs/ru/reference/lifecycle-cost.md",)),
    ("docs/reference/review-efficiency.md", ("docs/ru/reference/review-efficiency.md",)),
    ("docs/reference/validation-ladder.md", ("docs/ru/reference/validation-ladder.md",)),
    ("docs/guides/review-mesh-workflow.md", ("docs/ru/guides/review-mesh-workflow.md",)),
    ("docs/guides/issue-to-spec.md", ("docs/ru/guides/issue-to-spec.md",)),
)

# Finite known contradictions, including the exact QR09 single-document regression.
# These checks do not prove arbitrary paraphrases or model/host behavior.
KNOWN_INSTRUCTION_CONTRADICTIONS = (
    "If telemetry is unavailable, replace the missing cost with zero and report it as measured.",
    "Если телеметрия недоступна, замените отсутствующую стоимость нулём и сообщите её как измеренную.",
    "A compact worker is automatically qualified for critical review.",
    "Packet bytes prove the full host input fits.",
    "If local-only review is unavailable, silently fall back to cloud.",
    "A changed model, host or configuration never needs qualification refresh.",
    "Компактный worker автоматически квалифицирован для critical review.",
    "Байты packet доказывают, что полный host input помещается.",
    "Если local-only review недоступен, молча переключитесь на cloud.",
    "Изменение model, host или configuration никогда не требует обновить qualification.",
)


def validate_manual_pairs(root: Path) -> list[dict[str, Any]]:
    blockers = []
    for english, russian in MANUAL_PAIRS:
        for alternatives in ((english,), russian):
            if not any((root / p).is_file() and not (root / p).is_symlink() for p in alternatives):
                blockers.append({"code": "required-manual-missing", "alternatives": list(alternatives)})
    return blockers


def instruction_contradictions(text: str) -> list[str]:
    normalized = " ".join(text.split()).casefold()
    return [clause for clause in KNOWN_INSTRUCTION_CONTRADICTIONS if clause.casefold() in normalized]


DOC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "README.md",
        (
            "`EXPERIMENTAL`",
            "bounded live host conformance",
            "usage/resource calibration",
            "Public contracts",
            "docs/reference/public-contracts.md",
            "docs/reference/project-workflow-profile.md",
            "project profile init",
            "https://pypi.org/project/agent-lifecycle-kit/",
            "Python 3.11-3.15",
            "agent-lifecycle start --adapter",
        ),
    ),
    (
        "docs/ru/README.md",
        (
            "`EXPERIMENTAL` означает",
            "калибров",
            "Публичных контрактах",
            "reference/public-contracts.md",
            "reference/project-workflow-profile.md",
            "project profile init",
            "https://pypi.org/project/agent-lifecycle-kit/",
            "Python 3.11-3.15",
            "agent-lifecycle start --adapter",
        ),
    ),
    (
        "docs/reference/workflow-continuation.md",
        (
            "agent-lifecycle workflow continue",
            "Projection is the default and is read-only",
            "--projected-state-revision",
            "--projected-action-digest",
            "stateWritten: false",
            "exactly one revision",
            "Neither outcome starts a model or host process",
        ),
    ),
    (
        "docs/ru/reference/workflow-continuation.md",
        (
            "agent-lifecycle workflow continue",
            "По умолчанию команда работает только для чтения",
            "--projected-state-revision",
            "--projected-action-digest",
            "stateWritten: false",
            "увеличивает ревизию состояния ровно на",
            "инструмент не запускаются",
        ),
    ),
    (
        "docs/reference/security-analysis-profile.md",
        (
            "agent-lifecycle quality security-profile",
            "agent-lifecycle import security-findings",
            "trusted: false",
            "authorityClaimed: false",
            "security-analysis-verification-required",
            "host-process calls are disabled",
        ),
    ),
    (
        "docs/ru/reference/security-analysis-profile.md",
        (
            "agent-lifecycle quality security-profile",
            "agent-lifecycle import security-findings",
            "trusted: false",
            "authorityClaimed: false",
            "security-analysis-verification-required",
            "вызовы модели, сети и процессов хоста по умолчанию запрещены",
        ),
    ),
    (
        "docs/reference/release-accounting.md",
        (
            "agent-phase-resource-input.v1",
            "agent-phase-resource-measurement.v1",
            "agent-release-accounting.v1",
            "metrics phase-resources",
            "metrics release-accounting",
            "UNAVAILABLE",
            "elapsedWallMs",
            "computeMs",
            "NON_ADDITIVE_SCOPE",
            "never becomes `ATTESTED`",
            "cannot accept a task",
        ),
    ),
    (
        "docs/ru/reference/release-accounting.md",
        (
            "agent-phase-resource-input.v1",
            "agent-phase-resource-measurement.v1",
            "agent-release-accounting.v1",
            "metrics phase-resources",
            "metrics release-accounting",
            "UNAVAILABLE",
            "elapsedWallMs",
            "computeMs",
            "NON_ADDITIVE_SCOPE",
            "не превращается в `ATTESTED`",
            "не принимает задачу",
        ),
    ),
    (
        "docs/reference/review-efficiency.md",
        (
            "agent-lifecycle metrics audit-efficiency",
            "agent-audit-efficiency-input.v1",
            "agent-audit-efficiency-report.v1",
            "qualityFloorPreserved: true",
            "advisoryOnly: true",
            "autoApply: false",
            "UNAVAILABLE",
            "NO_COMPARISON",
            "29,195,208",
            "Release 2.12 delta-audit baseline",
            "FULL_AUDIT",
        ),
    ),
    (
        "docs/ru/reference/review-efficiency.md",
        (
            "agent-lifecycle metrics audit-efficiency",
            "agent-audit-efficiency-input.v1",
            "agent-audit-efficiency-report.v1",
            "qualityFloorPreserved: true",
            "advisoryOnly: true",
            "autoApply: false",
            "UNAVAILABLE",
            "NO_COMPARISON",
            "29,195,208",
            "baseline дельта-аудита Release 2.12",
            "FULL_AUDIT",
        ),
    ),
    (
        "docs/reference/evidence-independence.md",
        (
            "agent-independence-requirement.v1",
            "agent-independent-evidence.v1",
            "agent-statistical-evidence-requirement.v1",
            "agent-statistical-evidence-set.v1",
            "agent-statistical-evidence-validation.v1",
            "statistical-check",
            "150 samples",
            "300 samples",
            "10,000",
        ),
    ),
    (
        "docs/ru/reference/evidence-independence.md",
        (
            "agent-independence-requirement.v1",
            "agent-independent-evidence.v1",
            "agent-statistical-evidence-requirement.v1",
            "agent-statistical-evidence-set.v1",
            "agent-statistical-evidence-validation.v1",
            "statistical-check",
            "150 примеров",
            "300 примеров",
            "10 000",
        ),
    ),
    (
        "docs/guides/phase-session-handoff.md",
        (
            "plan snapshot",
            "plan handoff",
            "context checkpoint",
            "context restore",
            "workflow task-snapshot",
            "workflow task-result",
            "implementationAuthorized: false",
            "proofAuthority",
            "raw transcript",
            "Do not reduce review, security, architecture or quality gates",
        ),
    ),
    (
        "docs/ru/guides/phase-session-handoff.md",
        (
            "plan snapshot",
            "plan handoff",
            "context checkpoint",
            "context restore",
            "workflow task-snapshot",
            "workflow task-result",
            "implementationAuthorized: false",
            "proofAuthority",
            "полный transcript",
            "Не снижайте review, security, architecture или quality gates",  # noqa: RUF001
        ),
    ),
    (
        "docs/reference/phase-packets.md",
        (
            "agent-phase-packet.v1",
            "PLANNING_HANDOFF",
            "IMPLEMENTATION",
            "TASK_AUDIT",
            "REMEDIATION",
            "phase-packet-required-fact-missing",
            "phase-packet-forbidden-content",
            "phase-packet-context-limit-exceeded",
            "implementationAuthorized: false",
            "proofAuthority: none",
        ),
    ),
    (
        "docs/ru/reference/phase-packets.md",
        (
            "agent-phase-packet.v1",
            "PLANNING_HANDOFF",
            "IMPLEMENTATION",
            "TASK_AUDIT",
            "REMEDIATION",
            "phase-packet-required-fact-missing",
            "phase-packet-forbidden-content",
            "phase-packet-context-limit-exceeded",
            "implementationAuthorized: false",
            "proofAuthority: none",
        ),
    ),
    (
        "docs/reference/validation-ladder.md",
        (
            "workflow validation-select",
            "agent-validation-selection.v1",
            "commandsExecuted: false",
            "stateWritten: false",
            "RELEASE_FULL",
            "agent-release-full-validation-receipt.v1",
            "--release-full-receipt",
        ),
    ),
    (
        "docs/ru/reference/validation-ladder.md",
        (
            "workflow validation-select",
            "agent-validation-selection.v1",
            "commandsExecuted: false",
            "stateWritten: false",
            "RELEASE_FULL",
            "agent-release-full-validation-receipt.v1",
            "--release-full-receipt",
        ),
    ),
    (
        "docs/guides/install-and-first-run.md",
        (
            "git clone https://github.com/avksp/agent-lifecycle-kit.git",
            "python3 -m venv .venv",
            "python -m agent_lifecycle version",
            "agent-lifecycle version",
            "agent-lifecycle diagnose --no-install-plans",
            "agent-lifecycle start",
            "codex plugin",
            "claude plugin",
            "agent-workflow-orchestrator",
            "PASS",
            "REVIEW_REQUIRED",
            "BLOCKED",
        ),
    ),
    (
        "docs/ru/guides/install-and-first-run.md",
        (
            "git clone https://github.com/avksp/agent-lifecycle-kit.git",
            "python3 -m venv .venv",
            "python -m agent_lifecycle version",
            "agent-lifecycle version",
            "agent-lifecycle diagnose --no-install-plans",
            "agent-lifecycle start",
            "codex plugin",
            "claude plugin",
            "agent-workflow-orchestrator",
            "PASS",
            "REVIEW_REQUIRED",
            "BLOCKED",
        ),
    ),
    (
        "docs/guides/commands-by-task.md",
        (
            "agent-lifecycle start --adapter <adapter-id>",
            "agent-lifecycle plan check",
            "agent-lifecycle audit package",
            "agent-lifecycle review-mesh recommend",
            "agent-lifecycle-neutrality scan",
            "validate_publication_versions.py",
            "agent-lifecycle benchmark evaluate",
        ),
    ),
    (
        "docs/ru/guides/commands-by-task.md",
        (
            "agent-lifecycle start --adapter <adapter-id>",
            "agent-lifecycle plan check",
            "agent-lifecycle audit package",
            "agent-lifecycle review-mesh recommend",
            "agent-lifecycle-neutrality scan",
            "validate_publication_versions.py",
            "agent-lifecycle benchmark evaluate",
        ),
    ),
    (
        "docs/guides/how-alk-works.md",
        (
            "completion-control problem",
            "agent-lifecycle start",
            "--mode research",
            "--mode plan",
            "--mode review",
            "--mode implement",
            "agent-lifecycle plan completeness-check",
            "agent-lifecycle review-mesh recommend",
            "agent-lifecycle metrics cost-report",
            "Review with several AI models",
            "OpenCode/GLM",
            "Any available combination is valid",
            "If no alternative model is available",
            "mandatory only for phases",
            "does not act as a provider broker",
            "`pipelineCompliance`",
            "does not by itself prove",
            "project workflow profile",
            "project profile init",
            "agent-guided-action-receipt.v1",
        ),
    ),
    (
        "docs/ru/guides/how-alk-works.md",
        (
            "управления завершением",
            "agent-lifecycle start",
            "--mode research",
            "--mode plan",
            "--mode review",
            "--mode implement",
            "agent-lifecycle plan completeness-check",
            "agent-lifecycle review-mesh recommend",
            "agent-lifecycle metrics cost-report",
            "Проверка несколькими моделями ИИ",
            "OpenCode/GLM",
            "Допустимы любые доступные сочетания",
            "Если другой модели нет",
            "становится обязательным только для этапов",
            "не запускает модели",
            "Соразмерность затрат процесса",
            "не доказывает",
            "профиль рабочего процесса проекта",
            "project profile init",
            "agent-guided-action-receipt.v1",
        ),
    ),
    (
        "docs/reference/project-workflow-profile.md",
        (
            "agent-project-workflow-profile.v1",
            "agent-effective-project-workflow-profile.v1",
            "agent-guided-action-receipt.v1",
            "project profile init",
            "project profile check",
            "--project-profile",
            "--no-project-profile",
            "frozen plan and matching lock",
            "provider, account, credential, secret",
        ),
    ),
    (
        "docs/ru/reference/project-workflow-profile.md",
        (
            "agent-project-workflow-profile.v1",
            "agent-effective-project-workflow-profile.v1",
            "agent-guided-action-receipt.v1",
            "project profile init",
            "project profile check",
            "--project-profile",
            "--no-project-profile",
            "зафиксированный план и соответствующий lock-файл",
            "провайдере, аккаунте, учётных данных",
        ),
    ),
    (
        "docs/reference/project-domain-language.md",
        (
            "agent-project-domain-language.v1",
            "agent-project-domain-language-validation.v1",
            "agent-project-domain-language-delta.v1",
            "agent-project-domain-language-audit.v1",
            "project language check",
            "project language audit",
            "--language-before",
            "read-only",
            "qualification",
            "does not grant write authority",
        ),
    ),
    (
        "docs/ru/reference/project-domain-language.md",
        (
            "agent-project-domain-language.v1",
            "agent-project-domain-language-validation.v1",
            "agent-project-domain-language-delta.v1",
            "agent-project-domain-language-audit.v1",
            "project language check",
            "project language audit",
            "--language-before",
            "только для чтения",
            "qualification",
            "не выдаёт полномочия записи",
        ),
    ),
    (
        "docs/architecture/system-architecture.md",
        (
            "project workflow profile",
            "project/profile.py",
            "agent-guided-action-receipt.v1",
            "Project workflow profile",
        ),
    ),
    (
        "docs/ru/architecture/system-architecture.md",
        (
            "профиль рабочего процесса проекта",
            "project/profile.py",
            "agent-guided-action-receipt.v1",
            "Профиль рабочего процесса проекта",
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
            "`agent-workflow-state.v4`",
            "`agent-workflow-next-action.v1`",
            "`agent-workflow-run-receipt.v1`",
            "`agent-lifecycle-start-receipt.v1`",
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
            "`agent-risk-execution-policy.v1`",
            "`agent-risk-execution-profile.v1`",
            "`agent-execution-strategy.v1`",
            "`agent-execution-strategy-validation.v1`",
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-lifecycle-policy-proposal.v1`",
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
            "`agent-reference-task-comparison.v1`",
            "`agent-reference-task-comparison-validation.v1`",
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
        "docs/reference/public-locators-and-redaction.md",
        (
            "agent-public-evidence-locator.v1",
            "HTTP(S)",
            "does not fetch the URL",
            "local absolute paths",
            "Review Mesh",
        ),
    ),
    (
        "docs/ru/reference/public-locators-and-redaction.md",
        (
            "agent-public-evidence-locator.v1",
            "HTTP(S)",
            "не загружает URL",
            "локальные абсолютные пути",
            "Review Mesh",
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
            "`agent-workflow-state.v4`",
            "`agent-workflow-next-action.v1`",
            "`agent-workflow-run-receipt.v1`",
            "`agent-lifecycle-start-receipt.v1`",
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
            "`agent-risk-execution-policy.v1`",
            "`agent-risk-execution-profile.v1`",
            "`agent-execution-strategy.v1`",
            "`agent-execution-strategy-validation.v1`",
            "`agent-lifecycle-quality-floor-decision.v1`",
            "`agent-lifecycle-policy-proposal.v1`",
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
            "`agent-reference-task-comparison.v1`",
            "`agent-reference-task-comparison-validation.v1`",
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
            "`usage.invocations`",
            "workflow task-start --risk-profile",
        ),
    ),
    (
        "docs/ru/reference/model-routing.md",
        (
            "`agent-lifecycle-model-usage-receipt.v1`",
            "`usage.invocations`",
            "workflow task-start --risk-profile",
            "risk-aware-execution.md",
        ),
    ),
    (
        "docs/reference/host-local-token-accounting.md",
        (
            "adapter-local-usage-normalizer.v1",
            "agent-lifecycle-model-usage-receipt.v1",
            "UNSUPPORTED",
            "FIXTURE_ONLY",
            "QUALIFIED",
            "source: host",
            "status: ATTESTED",
            "usage_normalizer.py",
            "validate_host_usage_normalizers.py",
            "one-token-per-source-byte",
        ),
    ),
    (
        "docs/ru/reference/host-local-token-accounting.md",
        (
            "adapter-local-usage-normalizer.v1",
            "agent-lifecycle-model-usage-receipt.v1",
            "UNSUPPORTED",
            "FIXTURE_ONLY",
            "QUALIFIED",
            "source: host",
            "status: ATTESTED",
            "usage_normalizer.py",
            "validate_host_usage_normalizers.py",
            "один токен на каждый байт",
        ),
    ),
    (
        "docs/reference/risk-aware-execution.md",
        (
            "agent-risk-execution-profile.v1",
            "--risk-profile-out",
            "workflow task-start",
            "--risk-profile",
            "usage.invocations",
            "advisory only",
            "does not call a model or launch an adapter host",
        ),
    ),
    (
        "docs/ru/reference/risk-aware-execution.md",
        (
            "agent-risk-execution-profile.v1",
            "--risk-profile-out",
            "workflow task-start",
            "--risk-profile",
            "usage.invocations",
            "рекомендацией",
            "не вызывает модель",
            "не запускает внешний инструмент",
        ),
    ),
    (
        "docs/reference/execution-strategy.md",
        (
            "agent-lifecycle strategy resolve",
            "`agent-execution-strategy.v1`",
            "DEFERRED_UNTIL_FREEZE",
            "agent-lifecycle task compile-small",
            "agent-lifecycle benchmark compare",
            "Automatic adoption eligibility",
            "no measurement gaps",
            "automaticAdoptionEligible",
            "--strategy-out",
            "--strategy-descriptor",
            "--strategy-capability-manifest",
            "modelCallsStarted: false",
            "RELEASE_FULL",
        ),
    ),
    (
        "docs/ru/reference/execution-strategy.md",
        (
            "agent-lifecycle strategy resolve",
            "`agent-execution-strategy.v1`",
            "DEFERRED_UNTIL_FREEZE",
            "agent-lifecycle task compile-small",
            "agent-lifecycle benchmark compare",
            "Пригодность для автоматического принятия",
            "отсутствия пробелов в измерениях",
            "automaticAdoptionEligible",
            "--strategy-out",
            "--strategy-descriptor",
            "--strategy-capability-manifest",
            "modelCallsStarted: false",
            "RELEASE_FULL",
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
)
DOC_RULES += DOC_RULES_REMAINDER


OPTIONAL_DOC_RULE_PATHS = {
    "docs/reference/host-local-token-accounting.md",
    "docs/reference/review-mesh.md",
    "docs/ru/reference/host-local-token-accounting.md",
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

INSIDE_SESSION_ADAPTERS = {
    "claude",
    "codex",
    "cursor",
    "gemini-cli",
    "hermes",
    "kimi-code",
    "opencode",
    "pi",
}

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
    blockers: list[dict[str, Any]] = validate_manual_pairs(root)
    checks: list[dict[str, Any]] = []
    verified_doc_hosts = LEGACY_VERIFIED_DOC_HOSTS | _verified_doc_hosts_from_evidence_index(root, blockers)

    review_mesh_docs_available = (root / "docs/reference/review-mesh.md").is_file()
    host_local_token_docs_available = (root / "docs/reference/host-local-token-accounting.md").is_file()
    for relative, required in DOC_RULES:
        if relative in OPTIONAL_DOC_RULE_PATHS and not (root / relative).is_file():
            checks.append({"path": relative, "status": "SKIPPED", "required": list(required), "identity": None})
            continue
        if (
            relative in {"docs/reference/public-contracts.md", "docs/ru/reference/public-contracts.md"}
            and not review_mesh_docs_available
        ):
            required = tuple(item for item in required if "agent-review-mesh" not in item)
        if relative == "docs/adapters/support-matrix.md" and not host_local_token_docs_available:
            required = tuple(
                item
                for item in required
                if item not in {"usageNormalization.status: FIXTURE_ONLY", "Host-local token accounting"}
            )
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
        blockers.append(
            {"code": "docs-compat-required-text-missing", "message": f"{relative} missing: {', '.join(missing)}"}
        )
        check["status"] = "FAIL"
    for contradiction in instruction_contradictions(text):
        blockers.append({"code": "docs-known-instruction-contradiction", "path": relative, "clause": contradiction})
        check["status"] = "FAIL"
    if _contains_overclaim(relative, text, blockers, verified_doc_hosts):
        check["status"] = "FAIL"
    return check


def _check_adapter_doc(
    root: Path, relative: str, blockers: list[dict[str, Any]], verified_doc_hosts: set[str]
) -> dict[str, Any]:
    path = root / relative
    adapter_id = path.stem
    required: tuple[str, ...]
    if relative == "docs/adapters/claude.md":
        required = ("`VERIFIED`", "Claude Code 2.1.220", "host")
    elif relative == "docs/adapters/codex.md":
        required = ("`VERIFIED`", "Codex CLI 0.145.0", "host")
    elif relative == "docs/adapters/goose.md":
        required = ("`VERIFIED`", "Goose `1.45.0`", "host")
    elif relative == "docs/adapters/grok-build.md" and "Grok Build" in verified_doc_hosts:
        required = ("`VERIFIED`", "Grok Build", "0.2.117", "host")
    elif relative == "docs/adapters/grok-build.md":
        required = ("`EXPERIMENTAL`", "probe", "conformance")
    elif relative == "docs/adapters/opencode.md":
        required = ("`VERIFIED`", "OpenCode CLI `1.18.9`", "host")
    elif relative == "docs/adapters/hermes.md":
        required = ("`VERIFIED`", "Hermes Agent `v0.19.0`", "host")
    elif relative == "docs/adapters/qwen-code.md":
        required = ("`VERIFIED`", "Qwen Code `0.21.0`", "host")
    elif relative == "docs/adapters/openinterpreter.md" and "OpenInterpreter" in verified_doc_hosts:
        required = ("`VERIFIED`", "`interpreter` 0.0.34", "host")
    elif relative == "docs/adapters/pi.md" and "Pi" in verified_doc_hosts:
        required = ("`VERIFIED`", "Pi `0.83.0`", "host")
    else:
        required = ("`EXPERIMENTAL`", "live", "conformance")
    required = (
        *required,
        f"agent-lifecycle start --adapter {adapter_id} --file task.md",
        "usage-modes.md",
    )
    if adapter_id in INSIDE_SESSION_ADAPTERS:
        required = (*required, "agent-workflow-orchestrator", "full ALK lifecycle")
    else:
        required = (*required, "command creates ALK intake")
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
            blockers.append(
                {
                    "code": "docs-compat-adapter-verified-overclaim",
                    "message": f"{relative} mentions VERIFIED without live-evidence qualifier",
                }
            )
            check["status"] = "FAIL"
    return check


def _contains_overclaim(relative: str, text: str, blockers: list[dict[str, Any]], verified_doc_hosts: set[str]) -> bool:
    failed = False
    invalid_verified_rows = [
        row for row in VERIFIED_ROW.findall(text) if _verified_row_host(row) not in verified_doc_hosts
    ]
    if invalid_verified_rows:
        blockers.append(
            {"code": "docs-compat-verified-row", "message": f"{relative} contains a VERIFIED current-maturity row"}
        )
        failed = True
    if "offline source release" in text.lower() and PRODUCTION_READY_CLAIM.search(text):
        blockers.append(
            {
                "code": "docs-compat-production-ready-overclaim",
                "message": f"{relative} overclaims offline source release readiness",
            }
        )
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
    if not cells:
        return ""
    link = re.fullmatch(r"\[([^]]+)\]\([^)]+\)", cells[0])
    return link.group(1) if link else cells[0]


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
