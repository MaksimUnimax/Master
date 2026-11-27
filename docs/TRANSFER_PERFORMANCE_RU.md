# Сравнительная проверка производительности v30 → r3

Дата: 27 ноября 2026. Проверка A06/T05 выполнена на одинаковой синтетической IndependentUI fixture. Итоговая серия использует канонический private code commit `9fe2c75017874d0505b69086497d39c1fad72041`, runtime SHA256 `93da35e4222ce7f472d2579fc7aa3f180bc28c7c48cf85c220995d6a92624e25` и явный `HARNESS_DIALOG_ENGINE=native`.

## Условия и граница измерения

- v30 собрана в отдельном performance-v30-baseline из baseline + updates/master; все 27 overlay-файлов сверены по SHA256. Исходные деревья не изменялись.
- Каждый вариант импортирован в отдельном процессе; одна временная SQLite, один synthetic account, 2 материала, 3 изделия, 2 строки рецептуры, 2 хозяйственных события. Оба варианта завершили с coin_attempts=0.
- Один Chromium 158.0.8127.0 (/tmp/chromium), viewport 1440×1000, locale ru-RU, Python и полный Harness runtime одинаковы. Ключи/внешние провайдеры/Telegram отключены; сообщение помощнику не отправлялось.
- По 9 тёплых перезагрузок /app и 9 переходов: materials → products → summary, цикл трижды. summary — раздел «Сводка». Ещё одна загрузка после очистки browser cache вынесена отдельно.
- readyMs: wall time от команды Playwright до data-mode=member и enabled submit, затем один animation frame. Для перехода дополнительно ждём response body /api/accounting и видимый panel. Это наблюдение готовности через fixture с polling assertions, не LCP/INP и не чистое время сервера.
- p95: линейная интерполяция 9 наблюдений. Порядок baseline, затем candidate; без CPU/network throttling. Небольшая выборка и polling делают разницу порядка десятков миллисекунд шумной.
- asset bytes: ResourceTiming для /assets/ и /ui-assets/; HTML и JSON API не включены. transferSize включает overhead, decodedBodySize — тело ресурсов. На данном loopback стенде decoded и encoded совпали.

## Итоговые измерения exact r3

| Метрика | v30 | r3 | Разница |
| --- | ---: | ---: | ---: |
| Перезагрузка, p50, ms | 933.661 | 931.891 | -1.770 (-0.19%) |
| Перезагрузка, p95, ms | 949.987 | 935.926 | -14.061 (-1.48%) |
| Переходы, p50, ms | 58.074 | 60.228 | +2.154 (+3.71%) |
| Переходы, p95, ms | 76.012 | 70.674 | -5.338 (-7.02%) |
| API на одну перезагрузку, во всех 9 | 7 | 10 | +3 |
| Asset requests на перезагрузку | 14 | 21 | +7 |
| Тело assets на перезагрузку, байт | 174879 | 233229 | +58350 (+33.37%) |
| Asset transferSize на перезагрузку, байт | 179079 | 239529 | +60450 (+33.76%) |
| API на обычный переход, во всех 9 | 1 | 1 | 0 |
| Новые assets на обычный переход, байт | 0 | 0 | 0 |

Единственный cold reload: 936.434 → 468.413 ms. Он не входит в p50/p95. Одно наблюдение с polling готовности недостаточно для вывода о скорости.

Начальная страница загружает больше ресурсов и делает три дополнительных запроса. Обычные переходы не загрузили дополнительных файлов и не добавили API-вызовы. Разница локального времени мала и меняет направление между сериями; она не доказывает гарантированного ускорения или пользовательски значимого замедления. Порог PASS/FAIL по скорости не придуман. Production нагрузка, CDN, мобильная сеть и медленный CPU не моделировались.

## Откуда дополнительные запросы и байты

На /app добавились /api/assistant/preferences, /api/model-settings и /api/assistant/illustrations/settings. Старый /api/wallet заменён /api/wallet/balance, поэтому не добавляет ещё один запрос. Timer API при обычной загрузке не вызывается.

| Новый asset | Тело, байт |
| --- | ---: |
| /assets/account-finance.css | 3180 |
| /assets/account-finance.js | 10963 |
| /assets/coin-format.js | 591 |
| /assets/podmasterye-ai.css | 1209 |
| /assets/podmasterye-ai.js | 13988 |
| /assets/podmasterye-timer.css | 1466 |
| /assets/podmasterye-timer.js | 23968 |

Оставшаяся разница — изменения существующих podmasterye.js/css, extra.js и market-links.js. Все исходные и новые размеры с timing каждого файла сохранены в comparison.json.

## Черновик и корректность

В textarea введён один и тот же неотправленный текст. Все 9 переходов сохранили его в обоих вариантах. Все 9 перезагрузок страницы очистили его в обоих вариантах: сохранение между разделами проверено, переживание reload не реализовано ещё в v30. Это исходное поведение, оно не объявляется исправленным.

HTTP ошибок ≥400 — 0, page errors — 0, model usage — 0, coin_attempts — 0 в обоих вариантах. DB counts совпали. Итоговый сравнительный запуск завершён на exact r3 с native engine; source SHA проверен координатором.

## Воспроизведение и артефакты

В кандидат добавлен acceptance/transfer_performance.py; product runtime для измерений не менялся.
После распаковки ZIP переносимая команда из корня поставки использует входы `baseline/` и `source/`:

```bash
export HARNESS_DIALOG_ENGINE=native
export HARNESS_NODE_MODULES=/absolute/runtime/node_modules
export HARNESS_TEST_PYTHON=/absolute/runtime/venv/bin/python
export HARNESS_MEDIA_PYTHON="$HARNESS_TEST_PYTHON"
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/absolute/chromium
"$HARNESS_TEST_PYTHON" source/products/harness-platform/acceptance/transfer_performance.py \
  --baseline "$PWD/baseline/products/harness-platform" \
  --candidate "$PWD/source/products/harness-platform" \
  --output "$PWD/performance-recheck" \
  --samples 9
```

Пути runtime и браузера заменяются на установленные у сопровождающего.
Абсолютный `--output` необходим, поскольку каждый дочерний процесс меняет рабочий каталог.
Ниже сохранена фактически использованная команда исходной приёмки из `products/harness-platform`:

```bash
HARNESS_DIALOG_ENGINE=native \
HARNESS_NODE_MODULES=/workspace/scratch/c52d2397e3c5/test-runtime/node_modules \
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/tmp/chromium \
/workspace/scratch/c620787b5abf/billing_review_20261127/runtime/venv/bin/python \
  acceptance/transfer_performance.py \
  --baseline /workspace/scratch/c52d2397e3c5/performance-v30-baseline/products/harness-platform \
  --candidate /workspace/scratch/c52d2397e3c5/candidate/products/harness-platform \
  --output /workspace/scratch/c52d2397e3c5/context/performance-r3 \
  --samples 9
```

- context/performance-r3/comparison.json: полный итог с каждым наблюдением, запросом, размером asset, DB counts и hashes ключевых исходников. SHA256: `76be5ebbb177a2f5cd699b4b809ee154214de510745f2ce3bd3abc04efb26c20`.
- context/performance-r3-summary.json: канонический commit/runtime, сводные метрики и scope.
- context/performance-r3/{baseline,candidate}/measurements.json: отдельные результаты и screenshots.
- context/performance/comparison.json и context/performance-final/comparison.json: предыдущие диагностические серии на более раннем коде/окружении. Имя performance-final историческое; итоговым является performance-r3.

## Сохранённая вариативность прежних серий

| Серия | Reload p50 v30→candidate, ms | Reload p95, ms | Nav p50, ms | Nav p95, ms |
| --- | ---: | ---: | ---: | ---: |
| Предварительная | 922.280→929.884 | 939.861→959.783 | 60.391→59.634 | 62.180→72.863 |
| Повтор после исправления measurement harness | 926.114→939.000 | 942.616→970.858 | 66.062→60.987 | 75.694→89.606 |
| Итог exact r3, native | 933.661→931.891 | 949.987→935.926 | 58.074→60.228 | 76.012→70.674 |

Во всех сериях совпали API counts, body bytes, поведение черновиков и отсутствие HTTP/JS ошибок. Первоначальный harness оставлял служебные close-watcher задачи Playwright Response.finished при teardown; ожидание заменено на response.body. Прежние серии сохраняются как диагностика, не подменяют точный итоговый билд и не являются SLA.
