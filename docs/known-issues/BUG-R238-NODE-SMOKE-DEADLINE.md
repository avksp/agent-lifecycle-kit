# BUG-R238-NODE-SMOKE-DEADLINE

Status: OPEN. Cause: UNCONFIRMED.

## English

The Node syntax/export smoke exceeded its 15-second process deadline on Windows/Python 3.14.10 and 3.15.2. The 3.14.10 job also reported incomplete pipe cleanup. Both jobs stopped before the full test suite. [Failed CI](https://github.com/avksp/agent-lifecycle-kit/actions/runs/41512817738).

One fixed diagnostic batch ran the unchanged test once per exact Python version. Instrumented targets passed in 3.476 and 3.186 seconds, with completed children and closed pipes. Node file version 22.23.4 was observed after these targets. The Node version in the failing jobs was not recorded. [Diagnostic batch](https://github.com/avksp/agent-lifecycle-kit/actions/runs/41520002421).

The cause remains unknown. The observations establish no repair or release qualification. Original deadlines, output limits, cleanup guards, assertions and selectors stay in effect. New required failures block the release and remain in its evidence history. Causal work needs a failing-host child/startup/job/pipe-EOF timeline or another concrete causal fact.

## Русский

Проверка синтаксиса и экспортов Node превысила 15-секундный лимит на Windows/Python 3.14.10 и 3.15.2. В задании 3.14.10 также не завершилась очистка pipe-потоков. Оба задания остановились до полного набора тестов.

Один ограниченный диагностический пакет выполнил исходный тест по одному разу для каждой точной версии Python. Запуски с наблюдателем прошли за 3,476 и 3,186 секунды; дочерние процессы завершились, pipe-потоки закрылись. После наблюдений записана версия файла Node 22.23.4. Версия Node в исходных упавших заданиях не записана.

Причина не установлена. Наблюдения не подтверждают исправление и не дают допуска к релизу. Исходные лимиты времени, вывода, очистка, ассерты и выбор тестов сохраняются. Новые обязательные отказы блокируют выпуск и сохраняются в истории. Причинному исследованию нужна временная шкала создания/завершения процесса, Windows Job и EOF на упавшем хосте либо другой конкретный причинный факт.
