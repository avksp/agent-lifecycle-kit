# Учёт расхода жизненного цикла

Учёт расхода показывает, сколько токенов и шагов ушло на практическую работу,
проверку продукта, контроль жизненного цикла и координацию.

## Зачем это нужно

Проект должен помогать решать задачу, а не тратить большую часть бюджета на
самопроверку. Поэтому отчёты отделяют полезную работу от затрат на процесс.

## Команды

```bash
agent-lifecycle metrics cost-report --help
agent-lifecycle metrics recommend --help
agent-lifecycle policy adaptive-decision --help
agent-lifecycle policy tune --help
```

`metrics recommend` строит рекомендацию по режиму жизненного цикла.
`policy adaptive-decision` строит решение по нейтральным входам задачи:
task shape, SDD tier, риски, required evidence, попытки, context tokens и
resource caps. `policy tune` делает только рекомендательное предложение.
Применение требует явного `--apply` и отдельного пути `--output`.

USD-поля не обязательны для local и subscription моделей. Если metered host
нуждается в раннем запросе оператора, `meteredAskThreshold` указывается только
в metered budget policy и остаётся advisory; hard cap всё равно определяет,
нужно ли останавливать выполнение.

Adaptive policy принимает monetary metadata только для `budgetMode: "metered"`
и не использует её для выбора режима. Решение выбирается по токенам, времени,
числу вызовов, повторам и quality floor.

## Ограничение качества

Экономия не должна отключать обязательные проверки для релизов, адаптеров,
контрактов, миграций, задач с рисками безопасности и работ уровня S2.
