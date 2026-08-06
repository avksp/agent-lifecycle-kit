# Захват событий адаптера

Захват событий адаптера переводит активность хоста в нейтральные подтверждения
ALK. Адаптер объявляет эту возможность через операцию `adapter-event-stream` и
схему `agent-adapter-event.v1`; само объявление не повышает зрелость адаптера.

Поток событий должен проходить проверку
`agent-adapter-event-stream-validation.v1`. Завершённый поток включает старт
сессии, запуск задачи, завершение команды, сводку изменений и итоговое событие
задачи. Если задача заблокирована, поток должен завершаться `task.blocked`, а не
успешным текстовым сообщением.

```bash
agent-lifecycle adapter event-check \
  --event <adapter-event-1.json> \
  --event <adapter-event-2.json>

agent-lifecycle adapter event-capture-check \
  --descriptor <adapter.descriptor.json> \
  --capability-manifest <capabilities.manifest.json> \
  --receipt <event-stream-receipt.json> \
  --event <adapter-event-1.json>
```

Категории остаются общими: команда, изменение файла, переход жизненного цикла,
использование модели, решение пользователя и проверка. Ядро ALK не зависит от
внутренних названий событий конкретного хоста.
