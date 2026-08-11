# Порядок перевода адаптера в VERIFIED

Этот порядок нужен, когда один адаптер переводится из `EXPERIMENTAL` в
`VERIFIED` для конкретной версии хоста. Он не привязан к провайдеру: каждый
адаптер задаёт свои команды хоста, но контракт подтверждений и релизные проверки
остаются общими.

## Границы заявления

- Релиз исходников: отмеченное тегом содержимое репозитория и проверки без
  реального хоста. Он не доказывает одобрение публичного каталога или
  промышленную готовность.
- `VERIFIED` для хоста: одна версия хоста имеет ограниченную проверку реального
  запуска, калибровку расхода и финальное подтверждение жизненного цикла.
- Одобрение публичного каталога: внешняя проверка владельцем хоста. Она
  отделена от релиза исходников и уровня поддержки `VERIFIED`.
- Промышленная готовность: отдельные подписанные подтверждения CI, нейтральности,
  реального хоста, калибровки и независимого финального аудита. Это не часть
  обычного офлайн-релиза исходников.

## Этапы проверки

1. Предварительная проверка: записать версию CLI, готовность учётной записи,
   чистоту рабочего дерева, лимит вызовов, лимит токенов и лимит времени.
2. Пробный запуск: выполнить один ограниченный вызов хоста и проверить сведения
   о расходе до траты полного бюджета.
3. Проверка возможностей: построить декларативный план проб из манифеста
   возможностей. Сам план формирует вход для проверки уровня поддержки на
   реальном хосте.
4. Совместимость: создать подтверждение реального хоста для каждой обязательной
   операции из `conformance/core/adapter-baseline.v1.json`.
5. Калибровка: создать подтверждение расхода для каждого обязательного сценария
   из `conformance/core/live-calibration-profile.v1.json`.
6. Жизненный цикл: пройти ALK через старт задачи, результат задачи, приёмку,
   финальный аудит и финальное подтверждение.
7. Обновление дескриптора: изменить только нужный адаптер, указать проверенный
   диапазон версии хоста и обезличенные маркеры подтверждений.
8. Обновление документации: изменить матрицу поддержки, страницу адаптера и
   зафиксированное обезличенное резюме. Локальные сырые журналы не попадают в
   релиз исходников, если их специально не обобщили.
9. Финальная проверка релиза: запустить проверки документации, матрицы
   поддержки, кандидата релиза, нейтральности, упаковки и CI перед публикацией
   тега и GitHub Release.

## Секреты хоста

Используйте обычный для хоста источник учётных данных. Одни хосты применяют
интерактивный вход или хранилище ключей, другие обычно читают переменные
окружения. Для OpenInterpreter пользовательские провайдеры объявляют нужное имя
переменной через `env_key`; встроенные провайдеры используют свои
документированные имена.

Обвязки ALK могут получить приватный dotenv-файл через `--host-env-file`, но ни
одна переменная из него не передаётся дальше без явного
`--host-env-allow <NAME>`. Разрешённый список задаёт оператор: обвязка не должна
угадывать секреты по выводу хоста или записывать значения ключей в
подтверждения.

Отчёты и подтверждения могут хранить только метаданные
`agent-host-env-file-redacted.v1`: имена загруженных переменных, счётчики,
отпечаток пути и `valuesRedacted: true`. Перед принятием подтверждений
запускайте `validate_host_env_hygiene.py` с тем же env-файлом и разрешённым
списком, чтобы доказать отсутствие значений секретов в отчётах.

## Обязательные валидаторы

Используйте эти валидаторы вместо проверки только текстом:

```bash
python tools/release/validate_adapter_conformance.py \
  --baseline conformance/core/adapter-baseline.v1.json \
  --host <adapter-id> \
  --evidence <adapter-conformance-evidence.json>

python tools/release/generate_adapter_probe_plan.py \
  --profile conformance/core/adapter-probe-profile.v1.json \
  --manifest adapters/<adapter-id>/capabilities.manifest.json \
  --out <adapter-probe-plan.json>

python tools/release/validate_adapter_probe_evidence.py \
  --plan <adapter-probe-plan.json> \
  --receipt-dir <live-host-receipts-dir> \
  --out <adapter-probe-evidence-validation.json>

python tools/release/validate_live_host_conformance.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --baseline conformance/core/adapter-baseline.v1.json \
  --receipt-dir <live-host-receipts-dir> \
  --promoted-hosts <host-id> \
  --probe-plan <adapter-probe-plan.json> \
  --evidence <live-host-conformance-evidence.json>

python tools/release/validate_live_calibration.py \
  --profile conformance/core/live-calibration-profile.v1.json \
  --budget-targets conformance/core/budget-targets.v1.json \
  --receipt-dir <live-calibration-receipts-dir> \
  --promoted-hosts <host-id> \
  --evidence <live-calibration-evidence.json>

python tools/release/validate_support_matrix.py \
  --support-matrix docs/adapters/support-matrix.md \
  --profile plans/standalone-v1/.agent-plan/standalone-v1/ci-matrix-profile.v2.json \
  --evidence <support-matrix-evidence.json>

python tools/release/validate_docs_compat.py \
  --evidence <docs-compat-evidence.json>

python tools/release/validate_host_env_hygiene.py \
  --report <host-harness-report-or-receipt.json> \
  --host-env-file <private-host-env-file> \
  --host-env-allow <PROVIDER_API_KEY_NAME> \
  --require-host-env-report \
  --evidence <host-env-hygiene-evidence.json>
```

## Блокеры

Квалификация уровня поддержки блокируется, если нет обязательного
подтверждения, вместо реального запуска используется синтетическое
воспроизведение, расход не подтверждён, качество не имеет статуса `PASS`,
превышен бюджет, дескриптор не ссылается на подтверждения, матрица поддержки
не отражает подтверждения дескриптора, проверка проб обнаруживает расхождение
операций или документация намекает на публичное одобрение либо промышленную
готовность без внешних подтверждений.
