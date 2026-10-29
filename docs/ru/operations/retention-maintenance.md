# Хранение и удаление подробностей выполнения

ALK сохраняет cumulative financial totals, deduplication identities, closure records и hash-only summaries. Raw requests, diagnostics и captured configuration без credentials допускают логическое удаление **через 30 дней после authoritative full financial closure**. Завершение worker или task acceptance не запускает этот срок. Active runs, unresolved usage и financial exceptions сохраняют подробности. Это удаление файлов, а не физическое стирание носителя.

Запускайте существующий CLI от того же operating-system account:

```bash
agent-lifecycle workflow maintenance \
  --authority /absolute/private/root/maintenance-authority.json \
  --authority-sha <exact-raw-sha256> \
  --candidate-limit 32 --deadline <future-UTC-instant>
```

Authority и его private `.writer.json` sidecar уже должны принадлежать journal writer. Authority связывает canonical private root, journal identity и file, writer, storage version, reviewed manifest и lock. Закрепите raw SHA в run evidence и schedule. Нельзя создавать substitute authority ради принудительного cleanup. Переопределений `--journal` или `--private-root` нет.

У каждого вызова собственный исходный конечный deadline; ALK дополнительно ограничивает maintenance work 60 секундами. Hourly schedule должен вычислять свежий deadline при начале вызова. Повторное использование истёкшего literal timestamp не работает. Maintenance deadline не продлевает task или release deadline.

## Почасовой запуск на macOS

Используйте абсолютный Python executable ALK environment и закрепите source или installed package version. Сохраните следующий wrapper в private directory, замените три example paths/digest и разрешите исполнение только владельцу. Source checkout может задать точный `PYTHONPATH` в LaunchAgent; installed environment уже предоставляет package.

```python alk-maintenance-wrapper
from datetime import UTC, datetime, timedelta
import os
import sys

authority = "/absolute/private/root/maintenance-authority.json"
authority_sha = "<exact-64-hex-sha256>"
deadline = (datetime.now(UTC) + timedelta(seconds=45)).isoformat()
os.execv(sys.executable, [
    sys.executable, "-B", "-m", "agent_lifecycle", "workflow", "maintenance",
    "--authority", authority, "--authority-sha", authority_sha,
    "--candidate-limit", "32", "--deadline", deadline,
])
```

Установите user LaunchAgent в `~/Library/LaunchAgents/` с уникальным label, абсолютными Python и wrapper paths в `ProgramArguments`, `StartInterval` равным `3600` и private `StandardOutPath`/`StandardErrorPath`. Не используйте `KeepAlive`: отказ не должен создавать немедленный retry loop. Загрузите через `launchctl bootstrap gui/$(id -u) <absolute-plist-path>` и проверьте `launchctl print gui/$(id -u)/<label>`. Readback должен подтверждать installed command, hourly interval и точную конфигурацию. Ручной `launchctl kickstart` может проверить installed entry без ожидания часа.

User agent работает, пока доступна сессия пользователя. Sleep, logout, scheduler failure и missed runs могут задержать cleanup. Следите за actual receipts и outstanding due obligations; один installed plist не доказывает readiness. Чтобы остановить конкретный schedule, используйте `launchctl bootout` для его exact service и удалите только его plist/wrapper. Journal и financial history сохраняются.

Apple описывает scheduler в [Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html). Точные команды и keys установленной системы описаны в `man launchctl` и `man launchd.plist`.

## Другие платформы и отказ

Linux может запускать тот же pinned wrapper через hourly user timer. Windows может планировать ту же команду, но текущая raw-deletion implementation требует POSIX descriptor-relative no-follow operations. Она отказывает на unsupported platform до открытия authority или удаления файла. Timer, task definition или documentation сами по себе не квалифицируют платформу. Cleanup readiness разрешается только после actual installed-target observations безопасных permissions, file identities и removal на этой платформе.

`NOT_DUE` и `RUN_NOT_FULLY_CLOSED` сохраняют подробности. Due obligation, ожидающая больше двух часов, становится `OVERDUE`. Refusal или partial result должны оставаться видимыми и блокировать retention readiness. Устраните точную причину до явно ограниченного recovery; сохраните исходные failure и expense. Successful recovery удаляет каждый declared original/staging raw file и записывает `DONE`; totals, deduplication и closure summaries остаются доступными.

## Квалификация выпуска и ограничения host

Выбранный Codex route Release 2.16 ограничен ALK-controlled input на наблюдавшейся конфигурации Codex CLI 0.162.1 с private `CODEX_HOME` и documented `features.apps=false`. Whole-host input и financial usage остаются unavailable. Strong A5 protection и protected operator closing отказывают, если host не может установить требуемую границу. Двенадцать adapter source profiles описывают capability limits, но не доказывают двенадцать работающих native integrations или полный financial host enforcement.

Installed-target release probe использует изолированный, явно обозначенный financial fixture journal и реальные scheduler/CLI processes. Подготовка historical fixture отделена от maintenance: scheduler и deletion command всегда используют реальное текущее UTC. Local fixture receipt не может закрыть production run, снять hold или разрешить удаление из постороннего journal.
