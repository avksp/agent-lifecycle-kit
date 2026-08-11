# Дополнительные пакеты качества

Дополнительные пакеты качества описывают проверки, которые оператор может
включить явно, не меняя обычный путь жизненного цикла. Пакет
`agent-optional-quality-pack.v1` должен быть выключен по умолчанию, включаться
только явно, иметь лимиты ресурсов и не зависеть от конкретного провайдера в
ядре.

```bash
agent-lifecycle quality pack-check --manifest <quality-pack.json>
agent-lifecycle quality behavior-check --manifest <quality-pack.json> --fixture <behavior-fixture.json>
agent-lifecycle quality template-list
agent-lifecycle quality template-check --template-id bugfix
agent-lifecycle quality bug-recipe-list
agent-lifecycle quality bug-recipe-check --recipe-id reproduction
```

Если manifest не указан, CLI проверяет встроенный пакет. Негативные сценарии
успешны только тогда, когда ожидаемый отказ или блокировка действительно
обнаружены.

Шаблоны задач являются черновой помощью для планирования. Они выключены по
умолчанию, требуют явного выбора и не обходят проверку и фиксацию плана.

Рецепты профиля расследования ошибок описывают типовые этапы исправления
ошибок и переиспользуют существующие подтверждения воспроизведения, отпечатка
ошибки, гипотез, регрессионной проверки, влияния правки и перепроверки.
