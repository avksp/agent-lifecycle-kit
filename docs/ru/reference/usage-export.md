# Экспорт использования

`agent-lifecycle metrics usage-export` строит read-only экспорт из явно
переданных локальных JSON-артефактов. Команда не запускает реальные вызовы
хостов и не переводит использование локальных моделей в деньги.

Экспорт включает:

- adapter, session, run, task и operation id;
- digest подтверждений, найденные в исходных артефактах;
- input, output и total токены;
- шаги, длительность и ресурсные единицы, например context bytes или tool
  calls;
- необязательные решения по бюджету;
- необязательный `cost_usd` только как значение, сообщённое metered-хостом.

`cost_usd` не является каноническим учётом. Общий переносимый слой — это токены
и ресурсы. Ядро не содержит каталога тарифов и не оценивает денежный расход
локальных моделей.

```bash
agent-lifecycle metrics usage-export \
  --artifact work/run/model-usage.json \
  --project-root . \
  --format json \
  --out work/run/usage-export.json

agent-lifecycle metrics usage-export \
  --artifact work/run/model-usage.json \
  --format table \
  --out work/run/usage-export.txt
```

Выходные файлы создаются только один раз. Строковые поля из исходных артефактов
перед проверкой маскируются от локальных абсолютных путей и типовых секретных
маркеров.
