# Быстрый старт

Быстрый старт от установки до первой задачи под управлением ALK.

- Начните с руководства [Установка ALK и первый запуск](guides/install-and-first-run.md).
- Для конкретной команды откройте [Команды по задачам](guides/commands-by-task.md).
- Полный жизненный цикл описан в руководстве [Как работает ALK](guides/how-alk-works.md).
- Роли ALK, командной строки, модели и репозитория описаны в
  [архитектуре системы](architecture/system-architecture.md).
- Маршруты для двенадцати встроенных адаптеров собраны в разделе
  [Использование ALK с адаптером](adapters/usage-modes.md).

## Установка

macOS или Linux:

```bash
git clone https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell:

```powershell
git clone https://github.com/avksp/agent-lifecycle-kit.git
Set-Location agent-lifecycle-kit
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Подробное руководство описывает Python 3.11-3.14, установку из PyPI,
проблемы активации и типичные ошибки команды version. ALK также опубликован
в [PyPI](https://pypi.org/project/agent-lifecycle-kit/).

## Проверка установки

```
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
```

Если команда не найдена, снова активируйте виртуальное окружение или из корня
репозитория выполните `PYTHONPATH=src python -m agent_lifecycle version`.
Если версия неожиданная, проверьте `which agent-lifecycle` и
`python -m pip show agent-lifecycle-kit`. Остальные частые ошибки и решения
приведены в [руководстве по установке](guides/install-and-first-run.md).

## Запуск задачи из терминала

Для подробного запроса, плана или нескольких связанных Markdown-файлов
используйте файл:

```
agent-lifecycle start --adapter <adapter-id> --file task.md
```

Для короткого запроса передайте текст:

```
agent-lifecycle start --adapter <adapter-id> --text "Исследовать ошибку в кэше"
```

Если пока нужно только исследование, план или проверка, укажите режим:

```
agent-lifecycle start --adapter <adapter-id> --mode research --file research.md
agent-lifecycle start --adapter <adapter-id> --mode plan --file feature.md
agent-lifecycle start --adapter <adapter-id> --mode review --file proposed-plan.md
```

Обычный запуск создаёт входные данные для проверки. Реализация разрешается
только по структурированному запросу зафиксированной задачи. Полная
последовательность с профилем риска, возобновлением, импортом и проверкой
реализации приведена в разделе [Команды по задачам](guides/commands-by-task.md).

## Использование ALK внутри внешнего инструмента

Установите подключаемый модуль или общий навык по инструкции выбранного
адаптера, откройте целевой репозиторий и отправьте внешнему инструменту такой
запрос:

```
Используй навык agent-workflow-orchestrator для этой задачи.
Проведи задачу через полный цикл ALK: уточни запрос, составь и независимо
проверь план, зафиксируй его до реализации, проверь реализацию и заверши работу
только после принятия подтверждений и итогового доказательства.
Задача: <опиши задачу или укажи Markdown-файл>
```

Модель внешнего инструмента выполняет смысловую работу и использует инструменты
репозитория. ALK хранит состояние цикла, план, владельцев, границы изменений,
критерии приёмки, результаты аудита и подтверждения. Пользователь видит
следующее действие и понятный статус, например PASS, REVIEW_REQUIRED или
BLOCKED.

## Дополнительная проверка несколькими моделями ИИ

Review Mesh необязателен и по умолчанию выключен. Он принимает любые сочетания
доступных адаптеров и моделей. Для обычного процесса достаточно одной модели,
а несколько моделей добавляют независимый слой проверки.

```
reviewer-a: <выбранные оператором адаптер и модель>
reviewer-b: <другие доступные адаптер и модель>
reviewer-c: <необязательная третья проверка>
```

Откройте раздел [Review Mesh](reference/review-mesh.md), если зафиксированный
план включает дополнительную проверку. Внешние инструменты запускают выбранные
модели, а ALK сохраняет нейтральные идентификаторы, бюджеты, результаты,
статус редактирования и решение кворума.

## Что читать дальше

- [Установка ALK и первый запуск](guides/install-and-first-run.md)
- [Команды по задачам](guides/commands-by-task.md)
- [Практические сценарии жизненного цикла](lifecycle-cookbook.md)
- [Сценарии проверки кода](code-review-workflows.md)
- [Использование ALK с адаптером](adapters/usage-modes.md)
- [Настройка рабочего процесса и управления выполнением](reference/workflow-customization.md)
- [Архитектура системы](architecture/system-architecture.md)
- [Источник истины](reference/source-of-truth.md)
