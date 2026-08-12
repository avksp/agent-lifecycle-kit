# Установка адаптеров

Эта страница описывает порядок установки и проверки адаптеров. Статус адаптера
указан в матрице поддержки и определяется проверкой реального хоста,
калибровкой расхода и финальным подтверждением жизненного цикла.

Для старта следует начать с руководства [Установка ALK и первый
запуск](../guides/install-and-first-run.md). Эта страница содержит справочные
сведения именно об адаптерах.

Установка является только одним из способов работы. Различия между навыком ALK
внутри внешнего инструмента, командой `agent-lifecycle` в терминале проекта и
явным квалифицированным запуском процесса описаны в разделе [использование ALK
с адаптером](usage-modes.md).

## Общие проверки

```bash
agent-lifecycle adapter validate --descriptor adapters/codex/adapter.descriptor.json
agent-lifecycle adapter inspect --descriptor adapters/codex/adapter.descriptor.json
agent-lifecycle adapter install-plan --descriptor adapters/codex/adapter.descriptor.json
```

## Каналы публикации

По умолчанию установка идёт из неизменяемого тега с семантической версией.
Корневые манифесты плагинов и локальные проекции в адаптерах должны указывать
настоящую semver-версию в поле `version`. Записи маркетплейса используют
`source.ref: vX.Y.Z`, если хост устанавливает плагин из тега репозитория.

Плавающий канал `last`, если хост его поддерживает, допустим только как
отдельно включаемая ссылка на исходник, указывающая на принятый релизный
коммит. Он не должен становиться основным способом установки и не должен
заменять semver внутри `plugin.json`.

## Обновление установленного плагина

В Codex ссылка на точный тег закрепляется в источнике каталога. Команда
`codex plugin marketplace upgrade` обновляет данные того же источника. Для перехода на
новый принятый выпуск замените закреплённый источник и установите плагин
заново:

```bash
codex plugin remove agent-lifecycle-kit@agent-lifecycle-kit
codex plugin marketplace remove agent-lifecycle-kit
codex plugin marketplace add https://github.com/avksp/agent-lifecycle-kit.git --ref vX.Y.Z
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
codex plugin list
```

Claude Code использует обновление каталога и самого плагина вместо параметра
`--ref` в команде `plugin marketplace add`:

```bash
claude plugin marketplace update agent-lifecycle-kit
claude plugin update agent-lifecycle-kit@agent-lifecycle-kit
claude plugin list
```

После обновления перезапустите сессию хоста, чтобы она загрузила новые навыки и
метаданные плагина. Перед управляемой работой проверьте отображаемую версию.

## Локальные секреты хоста

Адаптеры, которые вызывают реальную модель, должны получать ключи через
штатный механизм хоста: переменные окружения, хранилище учётных данных хоста
или операторский запуск с секретами. ALK хранит в отслеживаемой конфигурации,
дескрипторах, артефактах подтверждения и релизных доказательствах только
обезличенные метаданные; ключи провайдера остаются в штатном механизме хоста.

Для обвязки реального хоста можно использовать `--host-env-file`, если ключ не
нужно экспортировать глобально. Это приватный файл оператора в стиле dotenv вне
репозитория; каждое имя переменной явно разрешается для конкретного запуска:

```bash
python tools/live_hosts/<host>_harness.py \
  --mode preflight \
  --host-env-file ~/.config/alk/hosts/<host>.env \
  --host-env-allow PROVIDER_API_KEY \
  --report work/<release>/evidence/<host>-preflight.json
```

Обвязка передаёт дочернему процессу хоста разрешённые имена и пишет в
подтверждения только `agent-host-env-file-redacted.v1`. Проверку отсутствия
значений секретов в отчётах выполняет `tools/release/validate_host_env_hygiene.py`.

Это правило относится ко всем адаптерам с переключаемыми провайдерами. Если
хост умеет переключать провайдеры или модели, выбранный провайдер остаётся
источником имени переменной и механизма учётных данных; ALK получает только
явно разрешённое оператором имя переменной для текущего запуска обвязки.

## Передача следующего шага хосту

Хосты, которым нужен единый детерминированный цикл, могут вызывать
`agent-lifecycle workflow run` перед запуском работы. Команда возвращает
следующее действие и причины закрытой остановки. Переходы состояния и работа
с моделью выполняются отдельными командами; секреты хоста в подтверждения не
попадают. Прямые запуски, ожидание, отмена и телеметрия остаются ответственностью
адаптера.

Если нужна точка входа ALK вокруг сессий адаптера, используйте
`agent-lifecycle adapter session start/status/resume/promote` или
`agent-lifecycle adapter run`. Эти команды создают
`agent-adapter-session-receipt.v1` и
`agent-adapter-session-resume-receipt.v1`, связывают управляемый запуск с
зафиксированным состоянием рабочего цикла и отделяют установку плагина от доказательства жизненного цикла. Текущие встроенные адаптеры объявляют
`managedLaunch.status: WRAPPER_ONLY`: квалифицированные профили задают маршрут
принятого запуска зафиксированной задачи.
Сводка: `docs/ru/adapters/managed-session-support.md`.

Codex, Claude Code, OpenCode и другие хосты могут показывать прогресс тем же
способом: после переходов жизненного цикла вызвать `agent-lifecycle report
progress --state <state> --terminal`, ограниченный режим `--watch` или
`agent-lifecycle report progress-bridge`. ALK читает только состояние,
подтверждённые хостом артефакты использования и счётчик изменений; разбор
телеметрии конкретного хоста остаётся в адаптере.

Уровни поддержки отображения прогресса перечислены в
`docs/ru/adapters/progress-bridge-matrix.md`; уровень поддержки адаптера
подтверждается отдельным набором доказательств.

Управляемые команды ALK также могут показывать прогресс напрямую при флаге
`--progress-hook stderr` или сохранять `agent-progress-hook-receipt.v1` через
`--progress-hook receipt --progress-receipt <path>`. Это включается явно.
Полный жизненный цикл фиксируется переходами состояния, проверками, аудитами и
принятыми подтверждениями.

## Codex

```bash
codex plugin list
agent-lifecycle adapter install-plan --descriptor adapters/codex/adapter.descriptor.json
```

Отображение прогресса: `WATCH` через отдельный терминал или обёртку после переходов
жизненного цикла.

## Claude Code

```bash
claude plugin list
agent-lifecycle adapter install-plan --descriptor adapters/claude/adapter.descriptor.json
```

Отображение прогресса: `WATCH`; телеметрия остаётся на стороне Claude Code, ALK
читает только переданные подтверждения.

## Cursor

```bash
cursor --version
agent-lifecycle adapter install-plan --descriptor adapters/cursor/adapter.descriptor.json
```

Отображение прогресса: `MANUAL`. Уровень `VERIFIED` для Cursor подтверждается
отдельным маршрутом проверки хоста.

## OpenCode

```bash
opencode --version
agent-lifecycle adapter install-plan --descriptor adapters/opencode/adapter.descriptor.json
```

Отображение прогресса: `WATCH`; нормализация телеметрии хоста остаётся в адаптере
OpenCode.

## Hermes

```bash
hermes --version
agent-lifecycle adapter install-plan --descriptor adapters/hermes/adapter.descriptor.json
```

Отображение прогресса: `MANUAL` после переходов рабочего цикла ALK.

## Qwen Code

```bash
qwen --version
agent-lifecycle adapter install-plan --descriptor adapters/qwen-code/adapter.descriptor.json
```

Отображение прогресса: `MANUAL`; телеметрия модели остаётся локальной для хоста.

## Gemini CLI

```bash
gemini --version
agent-lifecycle adapter install-plan --descriptor adapters/gemini-cli/adapter.descriptor.json
```

Отображение прогресса: `MANUAL`. Квалификация уровня поддержки Gemini CLI
проходит отдельным маршрутом.

## Goose

```bash
goose --help
agent-lifecycle adapter install-plan --descriptor adapters/goose/adapter.descriptor.json
```

Goose имеет статус `VERIFIED` только для Goose `1.45.0` на проверенной
локальной связке провайдера и модели. Продвижение по реальным проверкам
использовало ограниченные запуски без сессии и профиля, с явным провайдером и
моделью, а также проверкой чистого рабочего дерева после каждого вызова.

Отображение прогресса: `WATCH`; ACP остаётся за отдельной безопасной пробой.

## Kimi Code

```bash
kimi --version
agent-lifecycle adapter install-plan --descriptor adapters/kimi-code/adapter.descriptor.json
```

Отображение прогресса: `MANUAL`. Квалификация уровня поддержки Kimi Code
проходит отдельным маршрутом.

## Grok Build

```bash
grok --version
grok agent --help
agent-lifecycle adapter install-plan --descriptor adapters/grok-build/adapter.descriptor.json
```

Grok Build имеет статус `VERIFIED` для Grok Build `0.2.117` на проверенной
локальной связке провайдера и модели. Путь ACP остаётся закрыт проверочной
пробой, а неудачная проба фиксируется как подтверждение с закрытым отказом.

Отображение прогресса: `WATCH` через отдельный терминал или обёртку после шагов
жизненного цикла Grok Build.

## OpenInterpreter

```bash
interpreter --version
interpreter doctor --json
agent-lifecycle adapter install-plan --descriptor adapters/openinterpreter/adapter.descriptor.json
```

OpenInterpreter имеет статус `VERIFIED` для `interpreter` 0.0.34 на проверенной
локальной связке провайдера и модели. Учётные данные выбранной модели должны
быть видны процессу `interpreter` перед локальным повторным реальным запуском.
OpenInterpreter берёт имя нужной переменной из выбранного провайдера:
пользовательский провайдер указывает `env_key` в
`~/.openinterpreter/config.toml` или `.openinterpreter/config.toml`, а
встроенные провайдеры используют свои документированные переменные. Значение
ключа должно приходить из окружения или хранилища учётных данных хоста, а не из
конфигурации репозитория.

Чтобы дать ключ выбранного провайдера только процессу обвязки ALK, помести его
в приватный env-файл оператора и явно разреши это имя:

```bash
python tools/live_hosts/openinterpreter_harness.py \
  --mode preflight \
  --interpreter-model <model-id> \
  --host-env-file ~/.config/alk/hosts/openinterpreter.env \
  --host-env-allow PROVIDER_API_KEY \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens 1000 \
  --allow-live \
  --report work/release-1-18/evidence/preflight/openinterpreter-preflight-report.json
```

`PROVIDER_API_KEY` нужно заменить на имя env-key из выбранного провайдера.

Отображение прогресса: `MANUAL`; учётные данные провайдера и телеметрия
остаются вне ядра ALK.

## Pi

```bash
pi --version
agent-lifecycle adapter install-plan --descriptor adapters/pi/adapter.descriptor.json
```

Pi имеет статус `VERIFIED` для Pi `0.83.0` на проверенной локальной связке
провайдера и модели. Учётные данные выбранного провайдера должны быть видны
процессу `pi` перед локальным повторным реальным запуском. Имя env-key берётся
из документации или конфигурации выбранного провайдера Pi; ALK не хардкодит
имена секретов провайдера.

Чтобы дать ключ только процессу обвязки ALK, используй приватный env-файл
оператора и явно разреши переменную выбранного провайдера:

```bash
python tools/live_hosts/pi_harness.py \
  --mode preflight \
  --pi-provider <provider> \
  --pi-model <model-id> \
  --host-env-file ~/.config/alk/hosts/pi.env \
  --host-env-allow <PROVIDER_API_KEY_NAME> \
  --budget-mode subscription \
  --max-invocations 14 \
  --max-billable-tokens <token-cap> \
  --allow-live \
  --report work/<release>/evidence/preflight/pi-preflight-report.json
```

Проверенное заявление Pi относится к указанной локальной связке
провайдера и модели; сведения об ACP, публичном каталоге и промышленном
продвижении ведутся отдельно.

Отображение прогресса: `MANUAL`; учётные данные провайдера и телеметрия
остаются вне ядра ALK.

## Квалификация поддержки

Установка и квалификация поддержки являются отдельными шагами. Для уровня
`VERIFIED` нужны подтверждения реального запуска на конкретном хосте, учёт
расхода, принятые обезличенные доказательства и финальное подтверждение
жизненного цикла.
