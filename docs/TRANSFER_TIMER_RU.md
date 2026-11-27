# Перенос встроенного таймера Мастерской — TM01–TM06

Дата проверки: 27 ноября 2026. Изолированный candidate:
`candidate/products/harness-platform`.
База переноса обновлена до Master v30 (`2be1cf6`) и релевантных изменений Octoport
`dacb7114476cad88b34932ade4c03942a058060a`. Рабочие сервисы, их БД, ключи и
Telegram-получатели этим разделом не изменялись. Реальные внешние отправки не выполнялись.

Канонический private code commit: `9fe2c75017874d0505b69086497d39c1fad72041`.
Итоговый runtime SHA256:
`93da35e4222ce7f472d2579fc7aa3f180bc28c7c48cf85c220995d6a92624e25`.

## Результат и сервисные границы

Встроены шесть бесплатных хозяйственных отчётов, настройка расписаний, история
исполнений и отдельные статусы доставки в основной чат / Telegram. Таймер
доступен зарегистрированному аккаунту без установки плагина. Помощник умеет
читать расписания и готовить типизированный черновик; пользователь сохраняет
предпросмотр в штатной форме.

Это композиция уже существующего `user_plugins/timer`, а не второй scheduler.
Используются его события, черновики, очередь, файл лидерства и календарные
вычисления. Предметный runtime Мастерской исполняет только разрешённые операции
учётного ядра. В данных события нет токенов сессии, ключей провайдера, shell,
SQL, произвольного URL или неограниченного модельного поручения.

Числа берутся из `podmasterye_book.report`, `event_rows`, `aggregate`, `grouped`.
Таймер не создаёт собственные остатки, денежные формулы, wallet, grants или
оплату. Подтверждённая хозяйственная запись проходит через
`book.commit_action`, общий для HTTP, помощника и расписания.

### Карта реализации

| Требование | Реализация и граница |
| --- | --- |
| TM01 | `podmasterye_timer.initialize/activate/routes/assistant_capabilities`; builtin composition заменяет plugin entitlement только в Мастерской |
| TM02 | Общие `timer/store.py`, `schedule.py`; владелец/account workspace, chat, workshop binding, тип, план, channels, timezone, revision, status, next occurrence |
| TM03 | `podmasterye_timer_reports.py`: profit, sales, stock, purchases, production, tasks; период и допустимые фильтры; costCoins="0" |
| TM04 | Существующий `TelegramIntegration.send/status`; проверка lifecycle и integration pause; независимые delivery receipts |
| TM05 | Только ключи `book.FIELDS` и нормализованные arguments; каждый occurrence создаёт свежий preview, effect ждёт подтверждения владельца |
| TM06 | Один `jobs.Scheduler`, уникальный occurrence, атомарные claims, leases, fencing, recover, bounded retries, журнал, admin metadata |
| A02 | `capability_registry.py`: типизированные argumentSchema, роль/scope/effect/cost/confirmation/authority и ссылки на реальные HTTP/native/service handlers |

## Изменённые компоненты

- `platform_core/user_plugins/timer/schedule.py`: monthly, контракт календарного
  правила, политика пропущенных дат и DST.
- `platform_core/user_plugins/timer/store.py`: builtin gate через общий registry;
  legacy plugin composition сохранена для старого приложения.
- `platform_core/user_plugins/timer/jobs.py`: расширение существующей durable
  очереди, claims/leases, ограниченные повторы, runtime Мастерской и раздельная
  доставка. Legacy execution path остаётся в том же классе.
- `platform_core/podmasterye_timer.py`: scoped service contracts, HTTP, assistant
  drafts, действие с подтверждением, публикация и admin queue.
- `platform_core/podmasterye_timer_reports.py`: шаблоны, локальные периоды,
  разрешённые фильтры, полный JSON-результат и ограниченная текстовая сводка.
- `platform_core/capability_registry.py`: конкретные схемы и scope metadata для
  встроенных сервисов; неизвестная capability не получает фиктивную пустую схему.
- `platform_core/podmasterye_mcp.py`: mount `timer_list/timer_prepare`; при merge
  Master v30 сохранён operation grant без paid-only gate для локальных tools,
  добавлены v30 previousProposal и prepared revision рецептуры.
- `native/timer-exchange.mjs`: общий `appendLocalExchange` Octoport, совместимый
  `appendTimerExchange` wrapper; источник `harness-local/workshop-timer`.
- `native/timer-setup.mjs`: справка больше не сохраняет черновик; сохранение
  подтверждается только результатом вызова действия. Bidder/Ozon additions
  новой версии Octoport не переносились.
- `native/web/podmasterye-timer.js/css`: интерфейс владельца.
- `native/web/pm-admin-timer.html`, `admin-timer.js`: очередь и pause для админа.

Маршруты, lifespan, shell, навигация и обработка пустого user message подключены
координатором. Native worker принимает `timerExchange` и `localExchange` через
общий journal; mounted built-in MCP не требует установки marketplace plugin.

## Контракт расписания

Поддерживаются `once`, `interval`, `calendar` (ежедневно/по дням недели) и
`monthly`. Все instants хранятся в целых микросекундах UTC. Правило wall time
содержит IANA timezone. Проверка системного timezone сервера не участвует в
расчёте следующего occurrence.

| Ситуация | Принятое поведение |
| --- | --- |
| Разовая дата | ISO instant с timezone offset; прошлую дату нельзя сохранить. После scheduled occurrence — completed |
| Ежедневно | calendar с weekday 1–7, одно или несколько wall times |
| Еженедельно | Явный непустой список weekday и времён |
| Ежемесячно | Явные monthdays 1–31; число, которого нет в месяце, пропускается |
| Leap year | 29 февраля возникает только в существующую дату |
| DST gap | Несуществующее wall time пропускается |
| DST fold | Повторившееся wall time исполняется в первое вхождение |
| Пропущенные occurrences | Выполняется один самый ранний сохранённый occurrence; далее выбирается ближайшее будущее время, без массового backlog |
| Смена timezone/правила | Только через новый preview+save; новая revision; next occurrence рассчитан по новому правилу |
| Pause | `next_us=NULL`, текущие разрешения предыдущей revision отзываются; queued runs отменяются |
| Resume | Следующий будущий occurrence; restore аккаунта автоматически не возобновляет событие |
| Отмена | Событие и история остаются; новый запуск и редактирование отменённого события запрещены |
| Ручной запуск | Явная операция владельца, собственный request ID; может исполнять paused/completed событие, но не cancelled |
| Долгая работа | Lease 120 секунд, heartbeat каждые 40 секунд; чужая просроченная claim не может перезаписать новое владение |

Интерфейс показывает конкретные weekdays/monthdays, времена и timezone события.
Редактирование разового ISO instant с `Z` сохраняет тот же instant через явный
UTC offset. Пауза не снимается при редактировании.

У разового события абсолютный момент задаёт `at` с offset: смена только поля
IANA zone меняет его представление, а перенос момента требует изменить дату,
время или offset. Calendar/monthly интерпретируют wall times в новой зоне.
Interval отсчитывается от anchor: при неизменном правиле anchor сохраняется;
при изменении самого правила (включая zone) новый anchor — момент сохранения.

## Отчёты и периоды

| Шаблон | Данные | Допустимые фильтры |
| --- | --- | --- |
| profit | Авторитетная выручка, себестоимость, расходы, прибыль | products, channels |
| sales | Выручка, чистое количество с возвратами, группировки и продажи | products, channels |
| stock | Текущие остатки и дефицит, план пополнения | materials |
| purchases | Закупки периода и текущий план потребности | materials |
| production | Выпуск/незавершённое производство/партии | products |
| tasks | Активные задачи, сроки, напоминания, просрочка | task_categories |

Периоды: today, yesterday, last7, last30, previous_month, custom. Относительный
период вычисляется от даты occurrence в timezone события; stockAsOf отдельно
показывает дату текущего состояния учёта. Расчётный календарь учётного ядра
остаётся авторитетным: будущий ещё не наступивший для учёта период возвращает
понятную ошибку, не создаёт фиктивные записи.

Фильтры, которые не применимы к выбранному отчёту, отклоняются. При фильтрации
связанных объектов общие расходы без явной связи не распределяются
произвольно. В результате есть `filterNote`. Для подсчётов берётся полный
набор событий, а не только страница UI. Хозяйственные итоги вычисляются
исходными денежными функциями. Текст до 3800 символов подходит Telegram;
полный JSON хранится отдельно и доступен владельцу для скачивания.

Обычная сводка не запускает модель, не создаёт coin attempt и не требует
платного доступа. Возможный будущий модельный анализ остаётся отдельной
операцией общего биллинга.

## Предпросмотр, разрешения и действия

Preview истекает через 30 минут. Создание/редактирование принимается только с
последними draft ID, revision и receipt. Повтор request ID с теми же данными
возвращает сохранённый ответ; с другим payload — conflict. Scoped ownership
проверяется до записи и перед повтором, сведения о чужом событии не выдаются.

Запланированное хозяйственное действие не проводит запись само: в назначенный
момент `book.preview_action` формирует актуальные arguments и revision данных.
Proposal действует 15 минут. Владелец подтверждает его из истории исполнения.
В одной транзакции `book.commit_action` фиксирует effect и timer receipt.
Повтор подтверждения не создаёт вторую запись. Изменение данных, события,
состояния аккаунта, чужой scope или истечение срока блокируют effect.

Block/archive повышает revision всех событий владельца, в том числе уже
paused/completed, отменяет queued manual runs и отзывает все непринятые
preview receipts. Restore не возвращает старые полномочия. Проверен случай
готового результата плюс очередного manual run paused события плюс нового
черновика без target: после block→restore ни delivery, ни запись, ни принятие
старого черновика не происходят. UI скрывает истёкшие/отозванные preview и
сверяет action proposal с текущей event revision. Stale confirmation даёт
HTTP409; guest остаётся HTTP401, самостоятельный запрет прав — HTTP403.

Та же функция `account_lifecycle.revoke_timers` используется при архивировании
дополнительной мастерской: отзываются только события и черновики её bound chats.
Focused regression проверяет archive→restore, отмену старого queued manual,
запрет готовой доставки и старого preview. Событие основной мастерской сохраняет
revision, active и next occurrence, а его уже поставленный run исполняется один
раз. Общий account block по-прежнему отзывает все события владельца.

Таким образом принято первоначальное TM05 поведение «ожидает подтверждения».
Долгоживущего общего разрешения на любые будущие записи нет. Таймер не делает
отдельных бухгалтерских insert/update и не обходит принятый write contract.

## Исполнение и доставка

Уникальность обеспечена `UNIQUE(event,revision,due)` и отдельным request ID для
ручного запуска. Очередь захватывается атомарным `queued → reading` вместе с
lease token. Процесс-лидер владеет существующим файловым flock. Одновременно
исполняются до шести chat jobs с порядком внутри чата. Доставка имеет
независимые claims, до 16 records за проход, и не держит чужие очереди на
сетевом ожидании.

Безопасный read после истечения lease повторяется до пяти попыток. Неизвестная
внешняя запись не повторяется: событие ставится на паузу, outcome=unknown.
Результат local report сохраняется до доставки. Повтор доставки не вызывает
ни новый отчёт, ни хозяйственную запись.

Для чата используется durable native `timerExchange` с request ID
`timer_<run_id>`, затем идемпотентная проекция в `pm_turns`. Пустой user text
не создаёт фантомного пользовательского сообщения. Рестарт между native
публикацией и проекцией допускает безопасный replay.

Служебная публикация явно помечена `system=True`. Общая история пропускает
пользовательский row только у такого server-owned exchange; обычное сообщение
с пустым текстом и файлом сохраняется и получает attachments из авторитетной
native history. Regression включает mixed file-only + timer history, replay и
повторное открытие. Этим устранена найденная браузерным тестом потеря file-only
сообщения при слишком общей проверке `if text`.

| Telegram outcome | Поведение |
| --- | --- |
| Нет привязки / интеграция paused | disconnected, отчёт сохранён |
| Bot blocked | blocked; существующая интеграция обрабатывает отключение |
| HTTP rejection | rejected/failed; разрешён явный повтор доставки |
| Rate limit | pending с RetryAfter; ограниченные попытки |
| Network ambiguity или sending lease после сбоя | unknown; слепой автоматический и ручной повтор запрещён |
| Отзыв scope/lifecycle/revision | revoked; новые sends не выполняются |

Пользователь может повторить только failed/disconnected/blocked/rejected
доставку после актуальной проверки разрешений. Telegram, provider credentials
и session tokens не переносятся из Octoport. Живое подключение/внешний send
на новом домене этим evidence не подтверждены.

## HTTP и UI hooks

Основной префикс: `/api/chats/{chat_id}/timer`.

| Метод | Суффикс | Назначение |
| --- | --- | --- |
| GET | пустой | События, черновики, шаблоны, Telegram status, pagination |
| POST | `/preview` | requestId, definition, необязательные eventId+revision |
| POST | `/confirm` | requestId, draftId, revision, receipt |
| POST | `/events/{event}` | requestId, operation pause/resume/cancel/run, revision |
| GET | `/events/{event}/history` | Исполнения, результаты, deliveries; cursor |
| POST | `/drafts/{draft}/cancel` | Отмена ещё не принятого черновика |
| POST | `/runs/{run}/retry` | Явный повтор допустимой доставки |
| POST | `/runs/{run}/confirm` | Подтверждение конкретной хозяйственной записи |
| GET | `/runs/{run}/report.json` | Полный сохранённый результат |

`GET /api/admin/timer` показывает metadata, логин, event ID, статус, nextAt,
outcome и delivery, без названия/текста личного отчёта. Pagination 10/20/50/100.
`POST /api/admin/timer/pause` проверяет ID/revision, идемпотентен, пишет
`timer_admin_actions`. Администратор ставит на паузу; возобновляет владелец.

Hooks: `initialize(db)` внутри existing store._write; `activate(state)` в
lifespan; `routes(_token,_body)` и `admin_routes(_token,_body)`; UI
`PodmasteryeTimer.mount(host,{chatId,onRefreshChat,onAccountingChanged})`.
Применяются существующие cookie/bearer, CSRF и HTTP error handling.

## Миграции и откат

Все новые версии регистрируются общим `schema_migrations.apply`; отдельного
registry нет. Вызываются в одной транзакции identity store.

| ID | Изменение |
| --- | --- |
| `20261127_timer_engine_v1` | ALTER существующих timer_events/runs: domain, cancelled, lease/attempt/result/manual и delivery метаданные; индекс leases |
| `20261127_workshop_timer_v1` | builtin composition, workshop bindings, срок preview, idempotent control requests |
| `20261127_timer_admin_v1` | Идемпотентный audit админской паузы |

Существующие учётные и денежные данные не переписываются. Старые события имеют
domain=marketplace и не получают разрешение runtime Мастерской. Старый plugin
runtime не удалён. Повтор миграции сохраняет данные. При injected отказе ALTER
проверены откат транзакции/отсутствие ложной migration receipt и успешный retry.

В production этот код пока не запускался. Полный rehearsal выполнен на
обезличенной копии текущего состояния: четыре SQLite, 101 исходная таблица.
Все исходные таблицы остались неизменны, девять versioned upgrades применены,
повторное открытие и восстановление копии — PASS. В baseline отсутствовали
timer tables и старые jobs; миграция создала engine/store/admin таблицы, а
перенос старых событий для этого состояния не требовался. Все три timer ID
есть в общем migration registry. Native history сохранила один чат и 14
видимых сообщений, платных или внешних вызовов было ноль.

Доказательство итогового повторного rehearsal: `acceptance/migration-r3.json`;
процедура — в `../products/harness-platform/docs/TRANSFER_FINANCE_RU.md`.
Runtime SHA256: `93da35e4222ce7f472d2579fc7aa3f180bc28c7c48cf85c220995d6a92624e25`;
полный transfer manifest до записи окончательных отчётов:
`7e1f14157fb50b9119277775b733da7b003e47f23bfbe732f4c5c684901e72d6`.
Репозиторный JSON сохраняет counts/hashes/status, денежные агрегаты в нём
редактированы. Исходные live DB и credential files не изменялись.

## Предварительные отдельные проверки

Эта таблица сохраняет доказательства разработки timer-контура. Итоговый
полный Python и browser gate всего кандидата отражён отдельно в
`TRANSFER_ACCEPTANCE_RU.md` и `acceptance/requirements.json`.

Локально выполнены на полном установленном Harness 0.2.2-rc.1 из
`test-runtime/node_modules` и принятом runtime Python:

| Набор | Результат | Что проверяет |
| --- | --- | --- |
| `tests/test_timer.py` | 12/12 PASS | Весь исходный общий Octoport suite возвращён из compatibility archive в активные tests: календарь, draft revisions, concurrency, revocation, pagination |
| `tests/test_workshop_timer.py` | 34/34 aggregate + 1/1 focused PASS | Все виды расписания, DST/leap, isolation, replay/version, six report equality, помощник с действующим session-bound grant без записи до подтверждения, фильтры, cancellation, lease fencing, restart recovery, two schedulers/flock takeover, unknown TG, rate delay, account block→restore и selective workshop archive→restore revocation, confirmed action effect |
| `tests/test_workshop_timer_http.py` | 5/5 PASS | guest401, foreign404, nonadmin403, malformed400, forged409, CSRF403, no partial inserts, repeat confirmation, admin audit, stale proposal409 |
| `tests/test_workshop_timer_native.py` | 1/1 PASS, без skip | Реальный Harness: worker restart, same ID replay, exactly one assistant exchange, no empty user, cross-account isolation, changed payload conflict |
| `tests/test_capability_contracts.py` | 5/5 PASS | Валидные typed schemas, реальные bindings, enum/shape checks, no actor/key injection, book revision hash, no unimplemented delete |
| `native/timer-setup.test.mjs` | 2/2 PASS | Справка без write, подтверждение только actual action receipt, native action mount |
| `tests/browser/test_workshop_timer_ui.py` Chromium | 2/2 PASS | Создание/preview/edit monthly/pause/resume/run/reload/download/cancel, реальный scheduler+native chat, disconnected TG, admin pagination+pause/403/401 |

`tests/product-test-scope.json` больше не исключает общий `test_timer`.
Исключения старой оболочки plugin HTTP/journey/browser содержат точные ссылки
на новые применимые встроенные timer suites. Исходные archived tests не удалены.

Общий последний timer Python прогон: **57/57 PASS**, 15.699 секунд, включая
исходные 12 тестов и registry 5; повтор Chromium после финального UI timezone текста: 2/2 PASS,
7.447 секунд. Syntax checks Python и JS пройдены.
После выделения общей функции отзыва root выполнил отдельное изменение lifecycle;
focused `test_archived_workshop_restore_revokes_only_its_timer_authority` прошёл
за 0.404 секунды. Это дополнительный 58-й timer Python case, не новый общий
прогон 58 тестов.

Предварительные captures сохранялись в `timer-evidence/chromium`; этот путь
относится к среде разработки. Итоговая поставка содержит выбранные снимки
обоих полных прогонов в `evidence/screenshots/chromium` и
`evidence/screenshots/opera`: `timer-desktop.png`, `timer-report-mobile.png`,
`timer-admin.png`. Их исходные пути, размеры и hashes записаны в browser runtime
evidence. Desktop admin и 390px owner layout осмотрены; горизонтального выхода
документа не обнаружено.

Opera 141.0.6089.28 загружена из официального deb.opera.com и проверена по
официальному Packages SHA256:
`7e7b3c6bf62340718afae9519637cb8695ba0f9a6e09bfda7096d7c2d1f178ad`.
Первоначальная локальная среда блокировала process-singleton UNIX socket.
На Alisa настоящий бинарник Opera прошёл полный набор: **260/260 PASS**,
1813.823 секунды, в окне Xvfb. Chromium прошёл те же **260/260**,
1974.489 секунды. В обоих финальных наборах нет failures/errors/skips;
до и после проверены все 617 файлов источника. Режим без окна не прокручивает даже независимый
минимальный HTML через CDP wheel, поэтому его один отрицательный результат
сохранён как диагностика среды. Исходные assertions и runtime не изменялись.
Для воспроизведения предусмотрен общий `--headed` у browser runner;
результаты полного набора находятся в `acceptance/opera.json`.

Все outbound Telegram исходы в unit tests контролируются адаптером. Отсутствие
бота в реальном loopback UI проверено, внешний send не выполнялся. Ни платёж,
ни live provider image, ни реальная доставка Telegram этим набором не
принимаются.

Текстовые журналы focused-прогонов находятся в архиве:
`evidence/focused/timer-python.log`, `timer-registry.log`, `timer-setup.log`.
Итоговый полный набор и привязка к source-r3 имеют приоритет над этими
предшествующими focused-проверками.
