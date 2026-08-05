# Индекс подтверждений и импорт

Индексы подтверждений - это необязательные, пересоздаваемые резюме поверх уже
существующих артефактов жизненного цикла. Они помогают ревьюеру или маленькой
локальной модели найти нужное подтверждение без чтения всех файлов целиком.

Индекс не является источником правды. Он строится из явно переданных путей к
артефактам, хранит отпечатки и краткие поля, но не возвращает исходное
содержимое артефактов.

```bash
agent-lifecycle evidence index \
  --project-root . \
  --artifact evidence/final-proof.json \
  --out evidence-index.json

agent-lifecycle evidence search \
  --index evidence-index.json \
  --query final \
  --out evidence-search.json
```

Импорт планирования превращает недоверенный входной файл в черновой кандидат
ALK и проверочный артефакт. Кандидат остаётся `DRAFT`, содержит
`freezeBlocked: true` и требует обычной проверки плана, независимого аудита и
явной заморозки перед реализацией.

```bash
agent-lifecycle import plan --source incoming-plan.md --out imported-plan.json
agent-lifecycle import check --candidate imported-plan.json
```

Для задач через адаптер используйте тот же безопасный рубеж:

```bash
agent-lifecycle adapter task start --adapter codex --file task.md
agent-lifecycle adapter task start --adapter codex --task-text "Сначала проанализируй код перед внедрением функции"
```

Команда возвращает `agent-adapter-task-start-receipt.v1`. В receipt сохраняются
метка источника, отпечаток и размер в байтах, но не исходный текст задачи.
`--candidate-out <path>` сохраняет полный черновой артефакт импорта для
проверки.

Импорт блокирует типовые признаки секретов и локальные абсолютные пути до
создания кандидата.
