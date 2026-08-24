# Установка ALK и первый запуск

Установка из исходников подходит для изучения и доработки ALK. Пакет из PyPI
удобен, когда нужна только готовая команда.

## Что потребуется

Нужны:

- Git;
- Python 3.11, 3.12, 3.13 или 3.14;
- один поддерживаемый CLI, если модель должна работать внутри собственной
  сессии.

ALK устанавливается как пакет Python. Команда `agent-lifecycle` появляется в
активном окружении Python, поэтому активация окружения является частью
установки.

## Установка из GitHub

### macOS и Linux

```bash
git clone https://github.com/avksp/agent-lifecycle-kit.git
cd agent-lifecycle-kit
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m agent_lifecycle version
agent-lifecycle version
```

Пока работаете с исходниками, оставляйте `.venv` активным. Для следующего
запуска:

```bash
cd agent-lifecycle-kit
source .venv/bin/activate
```

### Windows PowerShell

```powershell
git clone https://github.com/avksp/agent-lifecycle-kit.git
Set-Location agent-lifecycle-kit
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m agent_lifecycle version
agent-lifecycle version
```

Если PowerShell запрещает активацию в текущем окне:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Для следующего запуска:

```powershell
Set-Location agent-lifecycle-kit
.\.venv\Scripts\Activate.ps1
```

## Установка опубликованного пакета

Для готового пакета также используйте отдельное окружение.

### macOS и Linux

```bash
python3 -m venv ~/.venvs/alk
source ~/.venvs/alk/bin/activate
python -m pip install --upgrade pip
python -m pip install agent-lifecycle-kit==1.83.0
python -m agent_lifecycle version
agent-lifecycle version
```

### Windows PowerShell

```powershell
py -m venv "$HOME\venvs\alk"
& "$HOME\venvs\alk\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install agent-lifecycle-kit==1.83.0
python -m agent_lifecycle version
agent-lifecycle version
```

[Пакет в PyPI](https://pypi.org/project/agent-lifecycle-kit/) поддерживает
Python 3.11-3.14. Точная версия синхронизирует команду, манифесты плагинов и
документацию.

## Проверка установки

Выполните команды в проекте, с которым будете работать:

```bash
python -m agent_lifecycle version
agent-lifecycle version
agent-lifecycle diagnose --no-install-plans
```

Первая команда показывает установленную версию. Вторая создаёт отчёт без
секретов и локальных абсолютных путей: проверяет пакет, профили, дескрипторы
адаптеров и доступные локальные подтверждения.

## Если `agent-lifecycle version` выдаёт ошибку

Сначала используйте форму, которая не зависит от отдельной консольной команды:

```bash
python -m agent_lifecycle version
```

| Сообщение | Что сделать |
| --- | --- |
| `command not found` или «команда не найдена» | Активируйте `.venv` и снова выполните `python -m pip install -e .`. Команда устанавливается в активное окружение. |
| `No module named agent_lifecycle` | Перейдите в папку исходников и установите пакет либо выполните `PYTHONPATH=src python -m agent_lifecycle version`. |
| `dataclass() got an unexpected keyword argument 'slots'` | Интерпретатор слишком старый. Используйте Python 3.11-3.14, создайте окружение заново и установите пакет. |
| Версия отличается от ожидаемой | Выполните `python -c "import sys; print(sys.executable)"` и `python -m pip show agent-lifecycle-kit`: активно другое окружение Python. |

Для исходного дерева:

```bash
cd agent-lifecycle-kit
PYTHONPATH=src python -m agent_lifecycle version
.venv/bin/agent-lifecycle version
```

PowerShell:

```powershell
Set-Location agent-lifecycle-kit
$env:PYTHONPATH = "src"
python -m agent_lifecycle version
.venv\Scripts\agent-lifecycle.exe version
```

## Первый запрос ALK

Есть два входа:

1. Команда в терминале создаёт ограниченную квитанцию ALK из текста или
   Markdown-файла.
2. Плагин или навык позволяет Codex, Claude Code, OpenCode и другим адаптерам
   работать по тому же жизненному циклу внутри сессии.

Через терминал:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --text "Исследовать ошибку в кэше и подготовить проверенный план"
```

Или передайте файл:

```bash
agent-lifecycle start \
  --adapter <adapter-id> \
  --file task.md
```

Обычный текст и Markdown поступают на стадию черновика, требующую проверки.
Команда фиксирует входные данные, но не превращает непроверенный запрос в
полномочие на реализацию. Идентификатор адаптера выберите в [матрице
адаптеров](../adapters/support-matrix.md).

## Установка плагина или навыка хоста

Для любого хоста порядок один:

1. установите плагин или подключите версию навыка;
2. перезапустите хост или перечитайте плагины;
3. откройте нужный проект;
4. явно попросите выполнить рабочий процесс ALK;
5. проверьте созданный план и квитанции до разрешения реализации.

Codex:

```bash
codex plugin marketplace add avksp/agent-lifecycle-kit --ref v1.83.0
codex plugin add agent-lifecycle-kit@agent-lifecycle-kit
codex plugin list
```

После установки перезапустите Codex. Claude Code:

```bash
claude plugin marketplace add avksp/agent-lifecycle-kit
claude plugin install agent-lifecycle-kit@agent-lifecycle-kit
claude plugin list
```

В активной сессии Claude Code выполните `/reload-plugins`. OpenCode загружает
навыки и JS-проекцию отдельно; команды копирования приведены на [странице
адаптера OpenCode](../adapters/opencode.md). Все варианты для комплектных
адаптеров собраны в [руководстве по установке адаптеров](../adapters/install.md).

После установки проверьте обнаружение пакета командой из раздела [проверка
Agent Plugins в клиентах](../reference/agent-plugin-qualification.md). Это
явная безопасная проверка, которая не заменяет жизненный цикл ALK.

В релизе 1.80 также описан необязательный контроль жизненного цикла внутри
адаптера. По умолчанию он не включён: комплектные адаптеры сейчас публикуют
`GUIDANCE_ONLY` и `NO_RECOMMENDATION`, а управляемый запуск сохраняет статус
`WRAPPER_ONLY`. Уровни операций, границы событий и правила квалификации точной
версии приведены в разделе [необязательный контроль жизненного цикла
адаптера](../adapters/lifecycle-control.md).

## Запрос внутри сессии хоста

После перезапуска или перечитывания плагинов отправьте такой запрос:

```text
Используй навык agent-workflow-orchestrator для этой задачи.
Сначала уточни запрос и подготовь проверенный план ALK.
Не переходи к реализации, пока план не проверен и не зафиксирован.
После реализации проведи обязательные аудиты и заверши работу только после
принятия подтверждений и итогового доказательства.
Задача: прочитай task.md и исследуй ошибку в кэше.
```

Модель выполняет уточнение, анализ и работу с кодом. ALK связывает план,
состояние, владельцев файлов, проверки, аудиты и принятые квитанции. Удачный
текстовый ответ сам по себе не означает завершение: пользователь видит
структурированный статус `PASS`, `REVIEW_REQUIRED` или `BLOCKED` с
артефактом и причиной.

## Следующие страницы

- [Быстрый старт](../quickstart.md) — короткий путь для следующей сессии.
- [Команды по задачам](commands-by-task.md) — полный указатель команд.
- [Использование ALK с адаптером](../adapters/usage-modes.md) — различия
  запуска в хосте и из терминала.
- [Настройка рабочего процесса](../reference/workflow-customization.md) —
  этапы, модели, промпты, тайм-ауты, повторы и несколько проверяющих.
- [Архитектура системы](../architecture/system-architecture.md) — роли ALK,
  хоста, модели и репозитория.
- [Проверка целостности плана](../reference/plan-verification.md) — проверка
  переданного пакета плана другим проверяющим до реализации.
