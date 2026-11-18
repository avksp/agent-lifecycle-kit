# Проверка цепочки запуска в CI

Запускайте `agent-lifecycle audit verify-chain` из доверенного пакета или
checkout. Репозиторий предоставляет доказательства. Владелец проверяющей
среды передаёт конфигурацию доверия и конечную отметку из отдельного
защищённого источника.

## Подготовьте доказательства

Выберите неизменяемую копию завершённого запуска в строгом режиме. Нужны
замороженный план и lock, набор пакетов задач, состояние и доступные из него
объекты, журнал, отчёты и применимые подписи. Начальный профиль поддерживает
один принятый план, один исходный допуск, одну попытку на задачу и одно
финальное решение. Для историй с повторами, продлением допуска или
дополнительными неподдерживаемыми решениями команда возвращает NOT_CHECKED.

Bundle задаёт относительные пути к плану, lock, состоянию, журналу и цепочке
квитанций. Используйте agent-chain-verification-bundle.v1. Цепочка содержит
SHA-256 сырых байтов всех использованных доказательств в выбранном запуске.
Пути самого bundle и цепочки исключены. Проверка отдельно выводит замкнутый
набор обязательных файлов из плана, состояния и журналов, затем сверяет
представленный инвентарь.

Конфигурация доверия закрепляет канонический хеш политики аудиторов и
политики оператора, если она применима. Конечная отметка связывает ID запуска,
пакет, план, исходный SHA, финальную ревизию и хеши bundle, lock, состояния,
журнала, цепочки и конфигурации доверия. Владелец проверки задаёт эти два
файла отдельно от каталога доказательств и защищает их от PR. Копирование
хешей из непроверенного PR не подтверждает их независимость.

Команда печатает один JSON и оставляет входные файлы без изменений. Код 0
означает успешную проверку выбранного объёма. Код 1 означает расхождение
или NOT_CHECKED. Код 2 означает невалидный селектор либо недоступный для
чтения вход. Отсутствующий артефакт в уже привязанном архиве даёт расхождение.
Выключенный режим подписей оператора отмечается как NOT_APPLICABLE.

## Настройте проверку

Запускайте этот workflow из защищённого источника. Назначьте репозиторий
владельца проверки и полный SHA его ревизии. В защищённом источнике находятся
trust.json и anchor.json. Владелец готовит образ с установленным CLI 2.51.0,
доступным по /usr/local/bin/agent-lifecycle, и закрепляет digest образа.
Образ и подключаемые каталоги содержат только необходимые для проверки
данные. Используйте checkout PR только как данные.
[GitHub Secure use](https://docs.github.com/en/actions/reference/security/secure-use)

```yaml
name: Verify selected run
on: pull_request
permissions:
  contents: read
jobs:
  verify-run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          path: evidence
          persist-credentials: false
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: OWNER/protected-verifier-inputs
          ref: REPLACE_WITH_FULL_REVIEWED_COMMIT_SHA
          path: verifier
          persist-credentials: false
      - env:
          CHAIN_VERIFIER_IMAGE: ghcr.io/OWNER/alk-verifier@sha256:REVIEWED_IMAGE_DIGEST
        run: |
          docker pull "$CHAIN_VERIFIER_IMAGE"
          docker run --rm --pull=never \
            --read-only --network none --user 65532:65532 \
            --cap-drop ALL --security-opt no-new-privileges \
            --env PYTHONDONTWRITEBYTECODE=1 \
            --mount "type=bind,src=$GITHUB_WORKSPACE/evidence,dst=/evidence,readonly,bind-recursive=disabled" \
            --mount "type=bind,src=$GITHUB_WORKSPACE/verifier,dst=/verifier,readonly,bind-recursive=disabled" \
            --entrypoint /usr/local/bin/agent-lifecycle "$CHAIN_VERIFIER_IMAGE" \
            audit verify-chain --repository-root /evidence \
            --bundle receipts/bundle.json \
            --trust-config /verifier/trust.json --anchor /verifier/anchor.json
```

Подготовка checkout и загрузка образа происходят до запуска проверки. Сделайте
оба каталога доступными для чтения выбранному UID, включая права прохода к
файлам. Контейнер получает только указанные каталоги. Запускайте его без
передачи секретов, токенов хоста и сокета Docker. Настройте обязательный статус
в защищённом workflow после проверки владельцем исходных данных. Пример
показывает границу контейнера. Независимость учётной записи и реальное хранение
ключей требуют отдельных доказательств.
[Режимы запуска Docker](https://docs.docker.com/reference/cli/docker/container/run/)

См. [происхождение решений ревью](../reference/audit-evidence-and-reviewer-provenance.md)
и [справочник CLI](../reference/cli.md).
