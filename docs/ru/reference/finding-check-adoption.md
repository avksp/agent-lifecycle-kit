# Связывание находки с проверкой

Релиз 1.86 связывает принятую находку аудита с детерминированной проверкой. Он
не создаёт второй реестр находок, не выполняет команду из квитанции и не выдаёт
разрешение на реализацию.

## Контракт

Контракт связывания называется `agent-finding-check-binding.v1`. В нём
фиксируются:

- идентификатор и дайджест находки;
- прошедшая проверку дельта плана и её пакет, ревизия, дайджест и исходная
  ревизия;
- символическая идентичность проверки (`id`, `route` и её дайджест);
- владелец, ограниченная область, исходная ревизия и ожидаемый результат;
- история переходов с явной авторизацией.

Идентичность проверки намеренно не является исполняемой командой. В ней нельзя
передавать `shell`, `exec`, `script`, `argv` или текст команды. За способ запуска
отвечает уже существующий маршрут проверки релиза или проекта.

## Жизненный цикл

Разрешён только следующий порядок:

```text
PROPOSED -> ACCEPTED -> IMPLEMENTED -> VERIFIED -> RETIRED
```

Каждый переход требует явно одобренной авторизации с актором и идентификатором
операции. Повтор того же перехода с тем же идентификатором идемпотентен; другой
идентификатор отклоняется. Для `IMPLEMENTED` и `VERIFIED` нужно только
читающее подтверждение. Для `VERIFIED` его результат также должен совпадать с
ожидаемым.

Предложение имеет только рекомендательный характер: в нём всегда указаны
`approvalRequired: true`, `applyAllowed: false` и `authorityClaimed: false`.
Оно не может ослабить план, заменить независимый аудит или объявить публикацию
в production.

## Последовательность CLI

Ниже используются JSON-артефакты. ALK читает их и создаёт новый артефакт; он не
запускает модель, хост-процесс или произвольную команду оболочки.

1. Создайте дельту плана и подготовьте находку, идентичность проверки и область.

   ```bash
   agent-lifecycle plan delta \
     --before plan-before.json --after plan-after.json --out plan-delta.json
   agent-lifecycle plan finding-check propose \
     --finding finding.json --delta plan-delta.json \
     --check check-identity.json --scope check-scope.json \
     --owner WS86-01 --source-revision "$SOURCE_REVISION" \
     --out finding-check-proposal.json
   ```

   `check-identity.json` содержит только `{"id": "...", "route": "..."}`.
   Маршрут обозначает существующий маршрут проверки, а не команду оболочки.

2. Проверьте рекомендательное предложение. Положительный результат всё равно
   требует явной авторизации.

   ```bash
   agent-lifecycle plan finding-check validate \
     --proposal finding-check-proposal.json
   agent-lifecycle plan finding-check accept \
     --proposal finding-check-proposal.json \
     --authorization approved-operation.json \
     --out accepted-transition.json
   ```

   Команда приёмки возвращает квитанцию перехода. Для следующих шагов используйте
   её поле `binding` как отдельный артефакт связывания.

3. Получите читающее подтверждение существующего маршрута проверки и свяжите его
   с принятой исходной ревизией.

   ```bash
   jq '.binding' accepted-transition.json > accepted-binding.json
   agent-lifecycle plan finding-check evidence \
     --binding accepted-binding.json --result PASS \
     --source-revision "$SOURCE_REVISION" \
     --evidence-id EV86-CHECK --out finding-check-evidence.json
   agent-lifecycle plan finding-check transition \
     --binding accepted-binding.json --target-status IMPLEMENTED \
     --authorization implemented-operation.json \
     --evidence finding-check-evidence.json --out implemented-transition.json
   ```

   После итогового результата то же подтверждение передаётся для перехода в
   `VERIFIED`. Изменение исходной ревизии, идентичности проверки, находки,
   дельты плана или дайджеста подтверждения приводит к безопасному отказу.

## Границы безопасности и полномочий

Связывание находки служит трассируемости, а не исполнению. Сохраняются такие
гарантии:

- дельта плана уже должна пройти проверку и оставаться связанной по lineage;
- потерянное, устаревшее или выведенное из действия связывание не может быть
  активным;
- подтверждение явно только для чтения и фиксирует нулевые запуски модели и
  хоста;
- квитанция не может заявить публикацию в production или полномочия
  независимого проверяющего;
- security-, architecture-, quality- и publication-гейты остаются обязательными
  и не заменяются результатом finding-check.

Полный набор публичных схем описан в разделе [Публичные контракты](public-contracts.md).
