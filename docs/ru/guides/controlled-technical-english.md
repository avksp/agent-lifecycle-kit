# Контролируемый технический английский ALK

Локальный профиль вдохновлён STE, но не заявляет соответствие или сертификацию ASD-STE100. Лицензированные manual и dictionary не воспроизводятся. Русский текст сохраняет смысл.

## Как писать инструкцию

Назовите actor и используйте активный глагол. Сначала условие, затем одно действие в предложении. Один термин — одно понятие; объясняйте незнакомые термины. MUST означает обязанность, MUST NOT / «не делайте» — запрет, MAY — возможность; нельзя ослаблять MUST до «желательно». Укажите evidence и условие отказа. Сохраняйте исключения, отрицания и порядок. Commands, paths, fields, enums, errors, hashes, units и limits остаются точными. Сокращение текста не даёт новых полномочий.

## Термины ALK

Draft не даёт execution authority. Frozen plan связывает reviewed matching inputs через lock; freeze сам не разрешает выполнение. Authorization разрешает выбранное native action. Attempt ограничен и сохраняет retry costs. Receipt связывает inputs и operation; существование файла не доказывает acceptance. Evidence подтверждает только заявленный scope. Independent review исключает самопроверку автора. Acceptance — существующий gated workflow transition. Projection не даёт authority. Refusal означает остановку, а не успех. Budgets конечны и после compact/retry. `UNKNOWN` / null остаётся неизвестным, а не измеренным нулём.

## Чтение по этапу

Полный hash-bound role contract, последнее user instruction и active packet обязательны дословно. Пути разрешаются от installed skill root; static resources поставляет package. Для recipe roles читайте начало cookbook, общий маршрут, таблицу выбора, safety rules, выбранный recipe и обязательные follow-ups. Меняйте recipe при смене этапа. Compilation и intake используют полные contracts без посторонних recipes; orchestrator выбирает фактический этап. См. [сценарии](lifecycle-cookbook.md).

| Задача | Role | Recipe |
| --- | --- | --- |
| Plan authoring, включая S0/S2 | `agent-first-planning` | Только исследование и планирование |
| Worker compilation | `agent-plan-to-workers` | Нет |
| Plan review | `audit-agent-plan` | Проверка папки Markdown-плана |
| Implementation audit | `audit-plan-implementation` | Аудит подтверждений реализации |
| Defect repair после явного opt-in | `bug-forensics` | Bug Forensics repair |
| Untrusted issue intake | `issue-to-spec` | Нет |

## Назначение подходящей роли

До назначения researcher, worker, reviewer или final auditor controller записывает risk, required tools, data policy, context/output limits и usage evidence requirements в существующих plan/packet inputs. Используйте provider-neutral classes и existing host-local profiles/evidence. Compact worker не является qualified critical reviewer. Сохраняйте independence, AC и quality floor независимо от цены или окна. Если local-only policy не допускает подходящего reviewer, остановитесь; нельзя молча переключаться на cloud. Packet bytes не измеряют full host input: при неизвестном input strict fit не доказан. Сохраняйте `UNKNOWN` / null и все расходы.

До назначения проверьте binding и freshness. Изменение model, host или configuration требует обновить только затронутую qualification. Для неизменного qualified route достаточно short preflight без нового benchmark или автоматического дорогого fresh review. Это guidance, а не selector, schema, gate или доказательство host enforcement.

## Измерение и review

Parity guards проверяют hashes, package bytes и bounded clauses, но не произвольный смысл, поведение модели или общее STE compliance. Считайте UTF-8 intervals и whitespace words (`len(text.split())`), включая Markdown/code: это не tokens, model calls или cost. Сохраняйте exact before/after bytes/hashes и тот же stage. Учитывайте полные role/shared contracts и все обязательные transitive links. Объединяйте пересечения внутри document/case; повторно учитывайте reuse в другом case. Missing sources означают `INCOMPLETE`. Сообщайте увеличения. Нельзя исключать обязанности или предполагать reuse после compact ради красивого числа. User/system/packet/host input вне этой projection. Равные S0/S2 authoring bytes не означают равную workflow cost. Независимый semantic review проверяет actor, condition, action, refusal, MUST/MAY, UNKNOWN, commands и schemas. Token savings и model behavior остаются UNAVAILABLE без сопоставимых измерений.
