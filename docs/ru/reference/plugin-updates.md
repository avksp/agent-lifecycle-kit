# Обновления плагина и влияние на планы

[English](https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/plugin-updates.md)

Проверка новой версии и совместимость активного запуска — разные результаты.
Файлы установленного плагина, загруженные инструкции, текущий Python runtime и
контракты плана имеют отдельные версии. Отсутствующие наблюдения — `UNKNOWN`.
Переданные пользователем версии хоста остаются декларациями; совпадение таких
значений не подтверждает совместимость.

Команды `plugin-update` проверяют метаданные, оценивают явно выбранные планы и
предлагают ручные штатные действия. Они не запускают модель, установщик или
фоновый сервис. Штатная установка, автоматический hook уведомлений и `safe-auto`
не квалифицированы. Их отказ не является успешным обновлением.

Создайте запрос:

```json
{"schemaVersion":"agent-plugin-update-request.v1","mode":"manual","channel":"stable"}
```

```sh
agent-lifecycle plugin-update check --request request.json --out available.json
agent-lifecycle plugin-update check --request request.json --cache updates.cache.json --out next-check.json
```

Точный `pin`, например `v2.48.0`, не переключается на другую версию. Для
предварительной версии нужны явная цель и канал. Проверка читает официальные
метаданные plugin ZIP из GitHub и wheel/sdist нужной версии из PyPI, привязывает
commit и проверяет версии, источник и состав публикации. Согласованные
метаданные не доказывают содержимое файлов или готовность установки. Отсутствие
исторического описания влияния означает неизвестную совместимость.

На вызов разрешены восемь HTTP-запросов, десять секунд, один МиБ суммарно и
256 КиБ на ответ; редиректов и автоматических повторов нет. Интервал кеша — час,
срок успешного наблюдения — 24 часа. Успех и ошибка возвращают явный кеш с
`lastAttemptAt`; ошибка добавляет `lastFailureReason`, сохраняя исходные
`observedAt` и candidate последнего успеха. До первого успеха оба поля null.
Если вызывающий сохраняет возвращённый кеш, в течение часа после попытки, включая
ошибку, HTTP не выполняется; результат ошибки — `UNAVAILABLE` или `STALE`. Старый
положительный кеш использует `observedAt` как время попытки. Это не process lock
и не глобальный scheduler: без сохранённого кеша и между независимыми процессами
общего интервала нет. Разрешённая работа не отменяется. `off` не обращается
к сети. Неподтверждённый trigger уведомления или `safe-auto` получает отказ до
вызова хоста, даже если вход утверждает, что trigger квалифицирован.

Метаданные читают ограниченные foreground Python-процессы: одна попытка запуска
на HTTP-попытку в пределах того же родительского deadline. Они не вызывают команды
обновления хоста. Отчёт отличает эти попытки от native-процессов хоста и реальной
сетевой телеметрии. Длинные описания пакета и заметки релиза исключаются до
проверки полей update-wire; хеш ограниченного исходного ответа сохраняется.
Лимит 4 096 символов относится к используемым полям идентичности и публикации.
Исключённый текст не передаётся модели и не интерпретируется как код.

Для оценки укажите явный список планов и описание целевой версии:

```json
{"schemaVersion":"agent-plugin-plan-inventory.v1","currentVersion":"2.47.0","plans":[{"manifest":"plans/feature/plan.manifest.json","lock":"plans/feature/plan.lock.json","state":"work/feature/run.state.json"}]}
```

```sh
agent-lifecycle plugin-update assess --request request.json --release release-impact.json --inventory inventory.json --repository-root . --out impact.json
```

Оценка использует штатную проверку целостности плана. Лимиты: 32 выбранных плана,
64 файла на план, 256 КиБ на файл, восемь МиБ уникальных входных байтов.
Каждый допустимый путь учитывается один раз; повторные чтения, включая другие
планы, должны совпадать с первым размером и хешем. `inputBytes` — уникальные байты,
`readBytes` — сумма чтений обёртки, без полного IO verifier или хоста. Другие проекты не
сканируются, команды проверок не исполняются, планы не изменяются. Лимит вывода
— 256 КиБ. Превышение даёт отказ, а не незаметно сокращённый успешный результат.
В этих границах поддерживаются плоские lock v1/v2. Scoped/v3 lock и
`extensions.reviewPolicy` требуют отдельного транзитивного набора доказательств;
оценка возвращает `UNKNOWN` до вызова такого verifier, не обходит его review и
runtime inventory и не запускает Git-команды.

Структурный и семантический результаты рассматривайте отдельно.
`NO_IMPACT_WITHIN_COVERAGE` относится только к проверенным идентификаторам.
Пробелы в схемах, командах, путях, профилях, хосте, качестве, review, evidence или
authority остаются `UNKNOWN`. Номер версии, прежняя схема или пустой список
изменений не доказывают сохранение смысла. Локальное описание и метки review
издателя — декларации, а не независимый аудит или разрешение установки.

Для DRAFT/REOPENED можно предложить точное изменение совпавшего литерала без
применения; изменённый смысл требует затронутого независимого review. Frozen
планы и lock сохраняются. Используйте пригодный прежний runtime либо reviewed
amendment. Для активной и приостановленной работы отложите активацию. Сохраняйте
завершённую историю, расходы, исходные часы и неудачные попытки. Нечитаемое
состояние не считается бездействующим.

Установка, перезапуск сессии и наблюдаемая проверка — отдельные действия.
Перед обновлением прочитайте [границы хоста](../adapters/plugin-updates.md).
ALK не обещает запрет независимого фонового обновления хоста или сохранение кеша.

Канонический shipped descriptor сохраняет `sourceCommit: null`: offer возвращает
`UNKNOWN` без команд. Непустой некорректный commit или несовпадение с объявленным
trusted commit дают отказ. Для локального связывания сохраните исходный
`release-impact.json` и точный `available.json`, сравните версию и содержимое
описания, затем создайте отдельный файл через `open("xb")`. Выполните Python-рецепт
из [English source](https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/plugin-updates.md):
он проверяет равенство `candidate.releaseImpact` исходному descriptor и версии,
подставляет только отдельно наблюдавшийся `candidate.sourceCommit` и печатает
SHA256 исходного descriptor, discovery и производного файла. Существующий файл
не перезаписывается. Затем выполните новую оценку с
`--release release-impact.observed.json` и прежней политикой запроса. Сохраните
хеши вместе с обоими входами. Производная копия остаётся `DECLARED`, канонический
источник сохраняет null; рецепт и локальный отчёт не аутентифицируют друг друга
и не дают полномочий на установку.

```sh
python - <<'PYTHON'
from pathlib import Path
from agent_lifecycle.contracts import canonical_bytes, load_json_object, sha256_hex
from agent_lifecycle.contracts.plugin_update_validation import (
    update_digest, validate_release_impact, validate_update_report,
)
source = Path("release-impact.json").read_bytes()
discovery = Path("available.json").read_bytes()
descriptor = validate_release_impact(load_json_object(source))
report = validate_update_report(load_json_object(discovery))
assert report["action"] == "check" and report["status"] in ("AVAILABLE", "CURRENT")
candidate = report["details"]["candidate"]
assert descriptor["sourceCommit"] is None
assert candidate["releaseImpact"] == descriptor
assert candidate["version"] == descriptor["version"]
derived = {**descriptor, "sourceCommit": update_digest(candidate["sourceCommit"], 40)}
body = canonical_bytes(validate_release_impact(derived)) + b"\n"
with Path("release-impact.observed.json").open("xb") as output:
    output.write(body)
print("canonical descriptor SHA256:", sha256_hex(source))
print("discovery report SHA256:", sha256_hex(discovery))
print("derived descriptor SHA256:", sha256_hex(body))
print("trust: DECLARED local derivation; no authority granted")
PYTHON
```
