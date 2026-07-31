# Sandbox boundaries

Sandbox boundaries — это необязательный слой структурированных подтверждений
для runtime-ограничений: filesystem, network, process и environment. Он
отделён от git write-scope.

## Разделение границ

`agent-worktree-attempt-receipt.v1` подтверждает, что задача изменила только
разрешённые пути репозитория в изолированном worktree. Этот receipt не
доказывает, что хост заблокировал сеть, запуск процессов, чтение переменных
окружения или доступ к файлам вне репозитория.

`agent-sandbox-receipt.v1` фиксирует runtime containment:

- `filesystem`: ограничения хоста или ОС для файловой системы.
- `network`: запрет, фильтрация или другой контроль сетевого доступа.
- `process`: контроль запуска процессов и дочерних процессов.
- `environment`: контроль доступа к переменным окружения и секретам.
- `enforcement.source`: кто обеспечил ограничение: `HOST`, `OS`,
  `CONTAINER`, `ADAPTER`, `EXTERNAL`, `UNKNOWN` или `UNSUPPORTED`.

Неизвестная поддержка фиксируется явно. Receipt или capability может быть
валидным со `status: UNKNOWN`, но high-risk задача, для которой sandbox
evidence обязателен, по умолчанию принимает только `PASS`.

## Policy

`agent-sandbox-requirement.v1` работает fail closed. Политика по умолчанию
требует passing sandbox receipt для high-risk классов задач: `S2`, `security`,
`release`, `external-environment`, `architecture` и `performance`.

Задача может включить требование напрямую:

```json
{
  "id": "WS-security-01",
  "tier": "S1",
  "executionPolicy": {
    "sandbox": {
      "required": true
    }
  }
}
```

Если sandbox evidence обязателен и отсутствует, проверка возвращает
`sandbox-receipt-required`. Если receipt структурно валиден, но имеет
`sandboxStatus: UNKNOWN`, проверка возвращает `sandbox-receipt-not-accepted`.

## Возможности адаптеров

Descriptor и capability manifest адаптера используют
`agent-sandbox-capability.v1`. Текущие адаптеры заявляют `status: UNKNOWN` и
`verified: false`, пока нет отдельного live sandbox receipt. Это не смешивает
зрелость адаптера с гарантией OS sandbox.

Адаптер может заявить более точный статус только при наличии evidence по всем
runtime boundary и enforcement source. Capability manifest обязан совпадать с
descriptor; drift приводит к FAIL.

## Публичные контракты

- `agent-sandbox-receipt.v1`
- `agent-sandbox-receipt-validation.v1`
- `agent-sandbox-requirement.v1`
- `agent-sandbox-requirement-validation.v1`
- `agent-sandbox-capability.v1`
- `agent-sandbox-capability-validation.v1`

Эти контракты не заявляют production promotion. Для promotion остаётся обычный
release evidence path.
