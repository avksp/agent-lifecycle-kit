# BUG-R238-STDIN-DEADLINE

Status: **OPEN**. Cause: **UNCONFIRMED**. No repair is claimed in 2.38.

## Observed failure

One Windows / Python 3.15.1 execution took 20.0379829 seconds with a 0.2 second
timeout and 0.2 second cleanup grace. The original test requires less than
3 seconds. Its managed child sleeps for 20 seconds while stdin receives
2,000,000 dummy bytes. The elapsed-time assertion failed. Later cleanup and
input-measurement assertions were not reached in that failing execution.
A recurrence may delay an operation beyond its requested timeout.

The test is
`tests.adapter_sessions.test_secure_launcher.SecureAdapterLauncherTests.test_ordinary_stalled_stdin_deadline_keeps_unknown_measurement`.
The original failure is in [CI 41425704694](https://github.com/avksp/agent-lifecycle-kit/actions/runs/41425704694),
job 125211669504. Other 14 platform cells and the old 22 critical checks passed.
These results do not establish the cause.

## Bounded follow-up

Two earlier controlled Python 3.15.1 targets passed. A final fixed series on
one Windows runner passed all six targets. The Python 3.14.9 control took
0.219974 seconds. Four fresh Python 3.15.1 isolates took 0.207858, 0.205502,
0.207933 and 0.210110 seconds. The same target after 654 executed cases took
0.204543 seconds. All target failures, errors and skips were zero. Six native
2 second watchdog stack files were empty. This series was not full-suite
qualification and does not prove that the delay cannot recur.

[Final series 41456287080](https://github.com/avksp/agent-lifecycle-kit/actions/runs/41456287080)
preserves the actual results. Three runtime files and the original test match
v2.37.0 bytes. Possible interactions remain unlocalized. Failed setup and
model attempts, job counts, unknown expenses and clocks remain in the release
history.

Local evidence is retained in the release workspace. These paths require that
workspace and are not public artifact links:

- `work/release-2-38/qualification/candidate-a2/diagnosis-windows315/DIAGNOSIS.json`
- `work/release-2-38/amendment-launcher-replication-a1/implementation/WS-LAUNCHER/FINAL-STOP.json`
- `work/release-2-38/amendment-launcher-replication-a1/implementation/WS-LAUNCHER/helper-completion-a1/qualification/BATCH-CLASSIFICATION.json`
- `work/release-2-38/amendment-launcher-replication-a1/EVIDENCE-INDEX.json`

## Release disposition and investigation trigger

The user selected A: retain this open defect and disclose the limitation.
There is no runtime or test fix, and no flaky or infrastructure classification.
Release 2.38 still requires one fresh full candidate CI, the original test as
an additional critical test with no skips, fresh package and current 19-case
consumer proof, and all normal native, final, main and publication gates.
Any required candidate or main failure stops automatic progress. A later
green CI does not close this item or erase the original failure.

Resume investigation only with new causal evidence matching this failure,
or a separately approved bounded strategy. Preserve original receipts, costs
and clocks. Record hypotheses and evidence before a minimal runtime repair.
Keep the original test and threshold. Close this issue only after a causal
repair and matching regression proof. Do not start probes or full reviews
merely to fill a metric.

## Русский

Статус: **ОТКРЫТ**. Причина: **НЕ УСТАНОВЛЕНА**. В 2.38 исправление не заявлено.
Один запуск исходного теста на Windows / Python 3.15.1 занял 20,0379829 с
при таймауте 0,2 с и запасе очистки 0,2 с. Порог теста — менее 3 с.
Проверки очистки и учёта ввода после упавшего утверждения не выполнились.
Другие 14 платформенных ячеек и прежние 22 критических теста прошли.

Два прежних контрольных наблюдения и все шесть целевых проверок последней
серии прошли. Последняя серия дала 0,204543–0,219974 с; целевой тест
после 654 выполненных случаев также прошёл. Ошибок и пропусков целевых
проверок не было, шесть файлов watchdog-стеков пустые. Полный CI эта серия
не заменяет. Неизменность трёх runtime-файлов и теста относительно v2.37.0
не устанавливает причину и не исключает влияние других изменений.

Пользователь разрешил сохранить дефект открытым и раскрыть ограничение.
Все проверки выпуска сохраняются; новый обязательный отказ останавливает
автоматическое продвижение. Даже зелёный CI не означает устранение причины.
Задержка может повториться. Возобновление исследования требует новых
причинных данных либо отдельно утверждённой ограниченной стратегии.
Старые доказательства, расходы и часы сохраняются. Закрытие возможно
после обоснованного ремонта и соответствующей регрессионной проверки.
