# Перенос аккаунта и единого финансового контура

Дата проверки: 27 ноября 2026. Область: AC01–AC04, FI01–FI05, финансовая часть A03–A05. Это отчёт по кандидату и его изолированной приёмке; выпуск в production не выполнялся.

## Результат

В кандидате подключены общий профиль, безопасность, управление сеансами, один кошелёк с историей и единая административная финансовая сверка. Используются существующие identity, session, coin_orders, coin_attempts, coin_grants и платёжный контур. Второй баланс или отдельная платёжная система не создавались.

Биллинг внешних сервисов перенесён из актуального Octoport как общий механизм. Каталог предметных платных сервисов пуст: рекламные parser.market/BHAPI-адаптеры не активированы для Мастерской. Регистрация нового сервиса требует серверного договора тарифа, единиц, квитанции и проверенного адаптера.

Учёт монет сохраняет целое число долей: 10^12 долей на монету. Доступный баланс и резерв показываются до сотых, API и история сохраняют точную сумму. Расход поставщика, клиентское списание, резерв, бонусы, платежи и возвраты представлены отдельно. Неизвестный расход обозначен как неизвестный, а не как нулевой.

## Источники и сохранённые контракты

Исходная точка реализации — точная локальная копия действовавшей Мастерской: `baseline/products/harness-platform`. Первичный снимок Octoport — release `3ed107921b202f238a0e8abbd860f7339040f76b`, сохранённый в `octoport-baseline/products/harness-platform`. Дополнительная сверка координатора выявила актуальные Master `2be1cf6` (v30) и Octoport `dacb7114`; их обновления включены в общий кандидат. Финансовые исходные модули в этой дельте не менялись. Для проверки реальных данных отдельно получена текущая read-only копия `/var/lib/private/podmasterye-stage`, а не синтетическое воспроизведение прежней схемы.

Прочитаны требования `TRANSFER_FUNCTIONALITY_RU.md`, аудит `ACCOUNT_ADMIN_AUDIT_RU.md`, финансовые документы Octoport `UNIFIED_SERVICE_BILLING_ARCHITECTURE_RU.md` и `UNIFIED_SERVICE_BILLING_IMPLEMENTATION_RU.md`, требования платформенных плагинов. В ходе сверки:

- `account_access.py` и существующий auth-контракт переиспользованы. Обязательные почта и TOTP администратора не ослаблены.
- Продуктовые `access_web.py` и `browser_session.py` сохранены: cookie и авторизация продуктов остаются раздельными.
- `checkout.py` сохранён, включая более свежую проверку подтверждённой почты для чека, подпись/проверку данных провайдера и фирменные тексты Мастерской. Оплата и возвраты не перенесены на новый путь.
- `service_billing.py` взят из указанного актуального Octoport и адаптирован через явный каталог, а не проверки имени продукта.
- Удалён отдельный финансовый расчёт из `podmasterye_services.usage`: старый путь исключал OpenRouter и приравнивал клиентские списания к себестоимости. Совместимый endpoint получает данные из общей проекции журнала.
- Существующий CLI `coin_review.resolve()` сохранён. Новый API использует тот же транзакционный расчёт и добавляет отдельный неизменяемый аудит.
- Старый алгоритм физического удаления аккаунта с удалением финансовой истории не переносился; жизненный цикл аккаунта находится в общей реализации `account_lifecycle`.

## Карта реализации

Все пути ниже относительно `products/harness-platform`.

| Файл | Назначение |
| --- | --- |
| `platform_core/coins.py` | Точный общий баланс; единый вход в provider metrics; lifecycle-проверка резервирования; исправлено отображение отрицательных дробных остатков |
| `platform_core/identity.py` | Существующие авторизация и сеансы; lifecycle gates; метаданные сеанса; совместимый wallet; единая проекция квитанций чата |
| `platform_core/service_catalog.py` | Серверный реестр сервисов/единиц/версий; известные модельные тарифы; без предметных рекламных интеграций |
| `platform_core/service_billing.py` | Проверенный общий механизм тарифов, квот, клиентской цены, резервов, dispatch, settle, конфликтов и идемпотентности |
| `platform_core/finance_schema.py` | Финансовые версии в единственном общеплатформенном registry |
| `platform_core/finance_reporting.py` | Общая проекция денег, расходов, потребления, источника, тарифов, курса, состояния и группировок |
| `platform_core/account_finance.py` | Профиль, сеансы, собственная история, admin report и атомарная ручная сверка с доказательством |
| `platform_core/finance_payments.py` | Admin список платежей, read-only конфигурация ЮKassa и восстановление через существующий checkout verifier с атомарным аудитом |
| `platform_core/coin_review.py` | Переиспользуемая транзакционная сверка; RUB/USD; сохранение авторизованного лимита клиента |
| `platform_core/podmasterye_services.py` | Совместимый административный отчёт из общего источника; HTTP403 для обычного пользователя |
| `native/web/account-finance.html` | Один раздел аккаунта: профиль, безопасность, сеансы, кошелёк |
| `native/web/account-finance.js` | Формы, точное округление через BigInt, единое обновление баланса с устранением одновременных запросов |
| `native/web/coin-format.js` | Единственный точный BigInt formatter итогов баланса/резерва для пользовательских и административных экранов |
| `native/web/account-finance.css` | Аккаунт и административные финансовые элементы, адаптивная компоновка |
| `native/web/pm-admin-finance.html` | Список и фильтры финансовых операций, отчёты и форма подтверждения |
| `native/web/account-finance-admin.js` | Административные запросы, фильтры, сортировка, пагинация и сверка по версии состояния |
| `tests/test_transfer_finance.py` | 20 содержательных проверок ledger, API, миграции, повторов, ролей, отрицательного остатка и сумм выше диапазона SQLite INTEGER |
| `tests/test_transfer_service_billing.py` | Приватный перенос общих upstream LedgerBoundaries/PriceLedger:17 test IDs,11 уникальных сценариев; только fixture и согласованная FI02 projection adaptation |
| `tests/test_transfer_finance_payments.py` | Семь проверок платёжной сверки: доказательство, идемпотентность, параллельность, роли, ошибки и конфигурация |
| `tests/browser/test_transfer_finance_ui.py` | Четыре браузерных сценария на реальном loopback-приложении |
| `scripts/verify_transfer_copy.py` | Read-only backup, обезличивание копий, точная проверка миграции/повторного запуска/восстановления и чтение native history |

`chat_api.py`, `web_ui.py`, основная навигация и административное меню монтируются координатором; вторую копию wallet panel убрали. Изменения находятся только в изолированном кандидате.

## API и точки подключения

`account_finance.routes(_token, _body)` подключается к существующему приложению. Используются существующие session/cookie, CSRF и строгий разбор полей.

| Метод и путь | Права | Контракт |
| --- | --- | --- |
| `GET /api/profile` | Действующий собственный сеанс | Логин, роль для отображения, известная дата регистрации; без произвольного изменения идентификатора/роли/почты |
| `POST /api/profile/password` | Существующий контракт | Текущий пароль, новый пароль; ротация текущего сеанса и отзыв остальных |
| `GET/POST /api/profile/security` | Существующий контракт | Почтовая защита пользователя; обязательную защиту администратора отключить нельзя |
| `GET /api/profile/sessions` | Собственный аккаунт | Непрозрачный ID, текущий сеанс, срок, запоминание, известные даты; token/digest не выдаются |
| `POST /api/profile/sessions` | Собственный аккаунт | `action=revoke,sessionId` или `action=others`; отзыв связанных grant, сохранение неизвестных расходов |
| `GET /api/wallet/balance` | Существующий собственный контракт | Точные `available` и `reserved`; лёгкий запрос обновления |
| `GET /api/wallet/history` | Собственный аккаунт | `offset`, `limit=10/20/50/100`, `kind`; начисления, покупки, возвраты, списания и резерв |
| `GET /api/wallet` | Совместимый существующий контракт | Сохранены charges и admin meters; добавлена пагинация, старый клиент работает |
| `GET /api/admin/finance` | Только администратор | `start,end,zone,login,provider,kind,state,operation,offset,limit,sort,direction` |
| `POST /api/admin/finance/reconcile` | Только администратор | `attemptId,version,amount,currency,reference`; атомарная сверка с идемпотентным аудитом |
| `GET /api/admin/podmasterye/usage` | Только администратор | Совместимая проекция общих period/provider/kind/account/payment/guest метрик |
| `GET /api/admin/payments` | Только администратор | Фильтры аккаунта/статуса/периода, страницы10/20/50/100, checkout/provider/request/refund IDs, точные суммы, read-only статус отдельной конфигурации ЮKassa |
| `POST /api/admin/payments/reconcile` | Только администратор | `checkoutId,version`; исключительно GET существующего provider payment и штатный `checkout.apply_payment`; без создания новой оплаты |

Сортировка финансов: дата, аккаунт, поставщик, точные списанные монеты и точный расход; неизвестная сумма остаётся в конце. Состояния: reserved, running, pending, settled, conflict. Неизвестные параметры состояния или сортировки не исполняются как произвольный SQL.

Даты model/service операций — время начала попытки, платежей — время создания checkout, возвратов — время подтверждения возврата. Это явно указано на экране. Дневные гостевые агрегаты сохраняют собственный исходный часовой пояс; неполное покрытие периода обозначается.

Экспорты UI:

```javascript
window.MasterAccount.open('profile' | 'security' | 'sessions' | 'wallet');
window.MasterAccount.select(tab);
window.MasterWallet.refresh();
window.MasterWallet.invalidate();
window.MasterWallet.format(exactDecimalString);
window.MasterCoins.format(exactDecimalString);
```

`MasterAccount.open` отправляет событие `master-account-open` для общей навигации; `select` открывает нужную вкладку. `#balance-label` сохранён. Событие `octo-wallet-refresh`, возвращение во вкладку и focus обновляют баланс через один механизм. Одновременно выполняемые шесть refresh дают один HTTP-запрос. История имеет защиту от применения устаревшего ответа. Пароли очищаются после успешной смены, черновик основного чата сохраняется.

## Финансовые инварианты

1. Общие `coin_orders` и `coin_attempts` остаются единственным денежным журналом. Каждый поставщик/тип — строки одного кошелька.
2. Новый платный резерв запрещён при неактивном аккаунте. Общий lifecycle проверяется в `_principal`, `_create_session`, `reserve_order`, generic reserve и dispatch. Совместимость с legacy без lifecycle row реализована общим модулем; неизвестный аккаунт после появления identity schema не считается активным.
3. Недостаток даже одной доли монеты относительно рассчитанного обязательного резерва отказывает до платной попытки. Две параллельные операции не резервируют одни и те же средства.
4. Подтверждённое списание неизменно; изменение тарифа/курса не переписывает историю. Неиспользованный резерв освобождается штатным settle/close_orders. Неопределённая попытка сохраняет резерв до доказательства.
5. Себестоимость OpenRouter берётся из provider receipt, а не из клиентского cap. Файлы/аудио используют подтверждённый `providerAmount`; late receipt сверх cap сохраняет полную себестоимость, но не повышает клиентский лимит.
6. Direct DeepSeek использует штатный неизменяемый рублёвый charge и сохранённый FX; legacy-конверсия остаётся исторической. Неизвестный тариф не приписывается DeepSeek.
7. Общие сервисы хранят supplier tariff, клиентскую unit price, единицы, receipt и quota snapshot отдельно. По неподдерживаемому тарифу ручной универсальный пересчёт запрещён: нужен зарегистрированный адаптер.
8. Классификация иллюстраций учитывает новый `period=assistant.illustration`, сохраняя совместимость с прежним source. Интернет, распознавание, аудио и изображения видны отдельными группами внутри общих provider totals и не суммируются повторно.
9. Неподтверждённые расходы дают `providerRub=null`, `costComplete=false`, число неизвестных и отдельно известную часть. Подтверждение нуля требует явной квитанции/основания.
10. Ручная сверка требует прав, актуального хэша состояния, суммы/валюты и ссылки/номера доказательства. Активный grant и активная web lease препятствуют сверке. Идентичный повтор возвращает replay; изменённые параметры конфликтуют. Аудит и ledger меняются в одной транзакции.
11. Платёжный grant не дублирует покупку в истории. Полный проверенный возврат показывает исходную покупку и отдельный возврат; событие возврата повторяется без второго списания.
12. Подтверждённый возврат после расходования покупки может дать отрицательный остаток. Исправлен существовавший дефект форматирования `divmod` отрицательных дробей: `-0.5` остаётся `-0.5`, одна отрицательная доля — `-0.000000000001`. Учётные целые значения не изменены.
13. Provider cost, внутренние receipt/usage/tariff/FX доступны только административным проекциям. Собственная история не содержит расходов или идентификаторов чужого аккаунта.
14. Гостевой классификатор — отдельный центр расходов сервиса, клиентские списания всегда ноль. Неполные агрегаты не объявляются полными.
15. Общеплатформенные начисления суммируются Python integer, а не SQLite SUM: два корректных больших кошелька могут превысить диапазон одного SQLite INTEGER. Проверена точная сумма `16000010` монет без переполнения и округления.
16. Администратор видит платежи из тех же `coin_checkouts`/`coin_refunds`, а не из отдельного payment state. Данные конфигурации показывают только готовность, чек, контрольный режим и маску shop ID; credentials, подтверждающие widget tokens, URL оплаты и email плательщика не выдаются.
17. Административная проверка ЮKassa выполняет только GET уже известного provider ID. Статус, paid/test, сумма, валюта, shop и metadata order проверяются существующим `checkout.apply_payment`. Права администратора и версия повторно проверяются после HTTP-ответа. Ledger и audit фиксируются в одной транзакции; параллельный webhook или повтор не начисляет монеты дважды.

## Неизвестные исходы и сообщения интерфейса

| Ситуация | Серверное правило | Интерфейс |
| --- | --- | --- |
| Попытка выполняется с действующим grant | Ручная сверка не допускается | «Выполняется», без кнопки подтверждения |
| Запрос завершился без доказательства расхода | Резерв остаётся, новый платный повтор не инициируется | «На сверке», неизвестная себестоимость и отдельно исходный резерв |
| Доказано, что вызов не отправлен или расход нулевой | Штатный zero settle освобождает резерв | Подтверждённый ноль; он не подставляется вместо неизвестного |
| Provider receipt есть, но клиентский debit ещё не согласован | Себестоимость и pending учитываются отдельно | Известный расход и незавершённая операция одновременно |
| Неизвестный service tariff | Требуется зарегистрированный адаптер квитанции | «Нужен адаптер сверки», без универсального ручного пересчёта |
| Устарела версия попытки/платежа | HTTP409, без изменения денег | Предложение обновить состояние |
| Активная web lease при попытке сверки | HTTP409, без изменения денег | «Интернет-запрос ещё выполняется» |
| ЮKassa недоступна или квитанция не совпадает | HTTP503/502, checkout остаётся прежним | Причина ошибки на экране, новый платёж не создаётся |
| Нет provider ID после неизвестного исхода создания оплаты | Автоматический POST/recreate запрещён | «Неизвестен исход создания» |
| ЮKassa выключена/не настроен поддержанный чек | Новая административная проверка не запускается | Read-only «Проверка недоступна»; управление live-конфигурацией отсутствует |
| Сеанс/права отозваны во время HTTP-проверки | Перед записью повторный principal/admin gate | Запись и audit не выполняются |

## Миграция

Версии: `20261127_finance_v1` и добавочная `20261127_finance_payments_v1`, общий механизм `platform_core.schema_migrations.apply`, вызываемый внутри store transaction. Отдельного registry нет; добавление платёжного аудита не меняет checksum ранее принятой finance_v1.

Добавляются:

- Общие service billing tables из Octoport; по умолчанию ни один предметный платный адаптер не включён.
- `identity_session_metadata`: непрозрачный ID, creation/last_seen, FK к действующему session digest. Для старых сеансов даты остаются NULL, вместо выдуманного времени миграции.
- `finance_reconciliations`: unique attempt, администратор, исходная версия, валюта и точная сумма поставщика, reference, точный charge и время.
- `finance_payment_reviews`: checkout FK, администратор, исходная версия/статус, подтверждённый статус/ID провайдера, хэш очищенной квитанции, сумма/RUB/время. Это аудит проверки, не второе состояние платежа.
- Индексы времени/checkout/аудита.

Проверяется ожидаемая исходная схема; общий checksum защищает принятую миграцию от скрытого изменения. Повторный запуск не создаёт новые IDs и не меняет деньги. Миграция аддитивная: balances, charges, holds, grants, identity/session records и usage operations не переносятся в новый ledger и не переписываются.

Проверка миграции использует сам неизменённый production-baseline код: дочерний процесс создаёт реальную прежнюю БД, аккаунт, сеанс и pending reserve `0.123456789012`; новый IdentityStore открывает эту БД. До/после побайтно по значениям сравнены все строки identity_accounts, identity_sessions, identity_session_preferences, coin_grants, coin_orders, coin_ruble_orders, coin_attempts, usage_operations. Доступный баланс, резерв, активность сеанса, FK и integrity_check сохранены. Повторное открытие также проверено.

Для автономного архива тест миграции требует замороженный baseline как внешний вход; при его отсутствии тест явно skip, а не заявляет проверку. В выполненной локальной приёмке baseline присутствовал, тест действительно выполнен. Для Alisa также подготовлен v30 baseline из обоих проверенных кодовых архивов; отсутствие baseline не используется как основание пропустить приёмку.

## Выполненные проверки

| Набор | Результат | Что подтверждает |
| --- | --- | --- |
| `tests.test_transfer_finance` | 20/20 PASS, 10.84 с | Точность, отрицательный refund, сумма выше SQLite INTEGER, параллельные резервы/сверка, миграция реального baseline, роли, изоляция, provider costs, неизвестные исходы, сортировка |
| `tests.test_transfer_finance_payments` | 7/7 PASS, 3.46 с | Recovery общей checkout engine, идемпотентность, concurrent requests, возврат роли во время HTTP, ложная/неполная квитанция, отключённая конфигурация, неизвестный provider ID, строгие API-поля |
| `tests.test_coin_wallet` | 2/2 PASS, 9.80 с | Существующий native chat wallet, concurrent turn, точное списание, unknown hold и возобновление |
| `tests.test_podmasterye_provider_v16` | 12/12 PASS, 25.49 с | Существующие provider/native пути, роли, отдельные расходы, повтор запроса, отказ и неизвестный исход |
| `tests.test_account_access` + `tests.test_checkout` | 22/22 PASS | Сохранённые auth/почта/TOTP/платёжные проверки и возвраты |
| `test_transfer_finance_ui.FinanceUI` + прежний v28 balance case | 5/5 PASS, 9.61 с | Реальные клики общего меню, формы/сеансы/черновик, история/точность/refresh/mobile, admin receipt, ЮKassa recovery и прежний UX balance |
| `tests.test_transfer_service_billing` (supplementary на Alisa, runtime r3) | 17/17 PASS, 26.329 с; 0 failures/errors/skips | Все общие upstream границы резервов/квот/credentials/повторов/себестоимости/priceVersion; неизвестность FI02 усилена |
| Полный основной Python gate на Alisa + supplementary service billing | 519/519 + 17/17 PASS; 2497.141 с + 26.329 с; 0 failures/errors/skips | 536 непересекающихся test IDs на frozen runtime r3, native engine, штатная изоляция файлов; 617 исходных файлов неизменны после проверки |
| Python compile / Node syntax | PASS | Новые и изменённые backend-модули, оба UI scripts |

Дополнительные общие проверки перенесены из приватных upstream `LedgerBoundaries` и `PriceLedger`. Сохранены 54 исходных assert calls после нормализации только fixture service names. В одном сценарии duplicate conflict точная известная сумма `0.2` проверяется через `knownProviderRub`; одновременно добавлены `providerRub is None`, `costComplete=False` и `unknownCostAttempts=1`. Это согласованная FI02 семантика неполной себестоимости, без изменения денежных значений, резервов, quotas или replay. Полное буквальное совпадение всех assertions не заявляется. AST-сверка и SHA исходников: `context/service-billing-regression-provenance.json`; результат и лог: `context/final-service-billing.json/.log`.

Этот дополнительный test file исполнялся вне immutable `source-r3`, импортируя именно его runtime. Основной gate из 519 тестов завершился отдельно без ошибок и пропусков; финальная матрица содержит 536 IDs (519 + 17). В `tests/product-test-scope.json` исключения названы на уровне только рекламных `FourProviders` и `PriceAdmin`, общий биллинг не исключён. Тест является производным приватного upstream и не включён в original-source public allowlist.

Браузерные сценарии поднимают штатный `create_app` через uvicorn на локальном адресе, используют отдельные аккаунты, реальную SQLite, httpOnly session cookie и synthetic mailbox. Весь UI работает через реальные HTTP-контракты. Административный финансовый тест использует доверенный тестовый вход; обязательная защита администратора независимо проверяется существующим auth-набором. За выполненные браузерные сценарии model usage journal не создавался.

Проверка кошелька: исходный точный остаток `19.543170450342` отображается как `19,54`, после начисления 2 монет событие обновляет шапку и wallet до `21,54`; история 24 записей делится 20+4; шесть одновременных refresh дают один balance request. Проверка сверки: неизвестный расход 0.001 USD при сохранённом FX 80 даёт charge 0.08, остаток 9.92, резерв 0, один audit row.

Снимки в `context/finance-browser`:

- `account-profile.png`
- `account-security.png`
- `account-sessions.png`
- `account-wallet-desktop.png`
- `test_wallet_exact_history_pagination_and_shared_refresh.png` — мобильный экран
- `test_admin_review_shows_unknown_then_atomic_receipt.png`
- `test_balance_rounding_preserves_exact_ledger.png`
- `admin-payment-recovery.png`

Браузерная проверка обнаружила реальное перекрытие account dropdown закреплённым заголовком рабочей области. Координатор поднял stacking context шапки; повторные обычные клики прошли без `force`. Числа в истории остаются читаемыми при узком экране через внутреннюю прокрутку таблицы.

## Реальный read-only backup на Alisa

Скрипт `verify_transfer_copy.py backup` получил SQLite backups при удерживаемых read snapshots, затем обезличил только копии в `/opt/podmasterye/candidates/functionality-transfer-v31/finance-migration/sanitized-baseline`.

- Основная БД:81 таблица/153 строки. Native journal:17/14, из них7 batches и6 dispatch. Public FAQ:1/23. Web admission:2/0.
- Source `stage.sqlite3`: SHA256 `14996ca4d9b2fae8e43c465975f50b900bac5a127aca5ea8c0e68b44d073f301` до и после.
- Source native journal: SHA256 `9a176b01e200f39c12ec042c18eacfad7678a86cc2a873ed06428e6f1051cf01` до и после.
- Хэши обеих дополнительных БД и usage journal также совпадают до/после. Все source connections открывались `mode=ro`, с `query_only`; source-записи не выполнялись.
- Counts, FK/integrity, точные финансовые поля, wallet fingerprint и структура native events сохранены при обезличивании. Использованы `secure_delete` и `VACUUM` копий; проверено отсутствие прежних credential bytes/контактов. Auth salts/hashes, sessions, recovery/TOTP, email, market credential blobs, Telegram binding и пользовательский текст заменены; технические relation IDs остаются для проверки связей.
- При создании обезличенной migration copy key-файлы, provider-keys, market key и Telegram configuration не копировались. БД и пользовательские тексты за пределы Alisa не переносились. В metadata-отчёт входят лишь количества, fingerprints и агрегаты; в репозиторном варианте точные денежные остатки скрыты, а hashes сохранены.
- В source отсутствуют timer tables, незавершённые попытки, оплаты, refunds и файлы-вложения. Хозяйственные book rows/events/products/materials пусты. Следовательно, реальная копия не доказывает сохранение непустых состояний этих типов; соответствующие границы покрыты синтетическими сценариями. Никаких legacy active marketplace timer jobs в этом source нет.

Полный локальный технический metadata-отчёт: `context/finance-backup-report.json`; вариант для исходников: `docs/acceptance/transfer-finance-production-copy.json`.

### Upgrade, повторное открытие и восстановление — PASS

Проверка повторно выполнена на Alisa из точного финального frozen candidate r3 (private code commit `9fe2c75017874d0505b69086497d39c1fad72041`): runtime SHA256 `93da35e4222ce7f472d2579fc7aa3f180bc28c7c48cf85c220995d6a92624e25`; manifest SHA256 `7e1f14157fb50b9119277775b733da7b003e47f23bfbe732f4c5c684901e72d6`. Исходная обезличенная копия сохранена отдельно, upgrade и restore выполнялись в `finance-migration/verified-93da35e4/upgraded` и `restored`.

- `passed=true`, `restorePassed=true`. После завершения upgrade/restore повторно проверены SHA256 всех пяти исходных production-файлов: они совпали с состоянием до backup (`unchangedSinceBeforeBackup=true`).
- Все 101 исходная таблица четырёх SQLite БД сохранены: для каждой старой таблицы сравнены все строки и значения всех прежних столбцов. Новые таблицы/столбцы допускаются; изменение исходных данных — ошибка проверки.
- Инициализация выполнена дважды. Созданы девять versioned migrations, включая finance/profile, payment audit, lifecycle, AI, permissions и timer. Повтор не меняет строки или суммы.
- После файлового восстановления upgraded-копии повторно выполнены инициализация и native history. Все строки всех таблиц, включая добавленные миграциями, совпали с upgraded состоянием.
- Штатный native worker прочитал один существующий чат: 14 видимых сообщений. Числа совпали после restore. Действия модели, таймеры, внешние API и платные вызовы не запускались.
- Финансовые fingerprints для grants/orders/attempts/ruble orders/checkouts/refunds/usage, точный wallet fingerprint, reserve и pending counts совпали. В source не было старых timer jobs; миграция создаёт пустые новые таблицы, без запуска legacy marketplace действий.

Технический отчёт: `context/finance-migration-report.json`; публикационно безопасный вариант без точных реальных денежных агрегатов: `docs/acceptance/transfer-finance-migration.json`. Обезличенные БД остались на Alisa и не входят в кодовый пакет.

Полный Python regression отделён от этой миграционной проверки. В локальном контейнере file isolation получает `ENOSYS` от Landlock, хотя Python parser dependencies установлены; guard не отключался. На Alisa штатный Landlock ABI 4 подтверждён. Финальный полный набор завершился на Alisa: 519/519 PASS за 2497.141 с, без failures/errors/skips. Дополнительные 17/17 service-billing тестов дают 536 непересекающихся test IDs. Итоговые файлы: `context/final-python.json/.log`, `context/final-service-billing.json/.log`, `context/python-runtime-r3.json`. После завершения процесса повторно проверены все 617 файлов исходного manifest: missing/changed пусты, runtime SHA256 сохранился.

## Полная закрытая копия для восстановления авторизации/config

Дополнительно 27 ноября 2026 в 11:50:47 UTC создан и проверен отдельный полный Master state/config backup на Alisa. Он содержит собственные auth/encryption/provider keys, 9 state files, 4 config files и эффективное окружение Master; 4 SQLite базы / 101 таблица / 190 строк. Archive SHA256 `6a216c831e85bc891df85e8e3bf027a076367e301b4b4948276c7159018ed21d`, каталог 0700, архив 0600, UID/GID 0:0. Источники до/после snapshot и restore совпали; восстановление выполнено только в отдельном закрытом каталоге, приложение не запускалось, Master остался active с тем же процессом.

Пути архива, безопасные метаданные и инструкция: `docs/acceptance/closed-backup-report.json`, `docs/MASTER_BACKUP_RESTORE_RU.md`. Raw backup, секреты и individual credential fingerprints остаются только на Alisa. Эта отдельная backup-операция не меняет факта, что live acceptance и обезличенная migration copy не копировали действующие ключи. Перед будущим deployment требуется свежая полная копия во время согласованной финальной паузы Master.

## Воспроизведение

Рабочий каталог: `/workspace/scratch/c52d2397e3c5/candidate/products/harness-platform`.

```bash
HARNESS_DIALOG_ENGINE=native \
HARNESS_NODE_MODULES=/workspace/scratch/c52d2397e3c5/test-runtime/node_modules \
/workspace/scratch/c620787b5abf/billing_review_20261127/runtime/venv/bin/python \
  -m unittest tests.test_transfer_finance tests.test_transfer_finance_payments tests.test_coin_wallet \
  tests.test_podmasterye_provider_v16 tests.test_account_access tests.test_checkout -v
```

```bash
HARNESS_DIALOG_ENGINE=native \
PYTHONPATH=.:tests/browser \
HARNESS_NODE_MODULES=/workspace/scratch/c52d2397e3c5/test-runtime/node_modules \
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/tmp/chromium \
PODMASTER_BROWSER_EVIDENCE=/workspace/scratch/c52d2397e3c5/context/finance-browser \
/workspace/scratch/c620787b5abf/billing_review_20261127/runtime/venv/bin/python \
  -m unittest test_transfer_finance_ui.FinanceUI \
  test_podmasterye_balance_v28_ui.BalanceV28UI.test_balance_rounding_preserves_exact_ledger -v
```

Node runtime установлен отдельно через `npm ci --ignore-scripts` по candidate `deploy/runtime/package-lock.json`, без изменения общего runtime или исходного lockfile. В нём присутствуют @deepseek-ai/dsh 0.2.2-rc.1, fflate, libreoffice-kit, sharp и прочие зависимости штатного native worker. Рабочий browser — @sparticuz/chromium 158.0.0 из отдельного `test-browser`; стандартный `/usr/bin/chromium` в этом контейнере является launcher без бинарника, Playwright CDN возвращал403. Из npm package распакован `/tmp/chromium`; рабочие тесты действительно запускались на нём.

### Окружение финального серверного набора

Финальный общий runner завершился из `source-r3` с `HARNESS_DIALOG_ENGINE=native`, как в фактических службах Master и Octoport (координатор подтвердил read-only просмотром `/proc`). Пропуск этого флага выбирает legacy-ветку и не представляет production-конфигурацию. Диагностический запуск без флага сохранён отдельно и не считается итоговым gate; точечный сценарий единого контекста с native прошёл 1/1 за 20.992 с без изменения исходников.

В тестах используются read-only Python/Node из `/opt/harness-prod/runtime/attachments-06f257269dd3`. Фактический прежний Master указывает Node modules `/opt/harness-prod/runtime/native-dialog-b667280/node_modules`; эти пути явно разделены в provenance, успешный тест не является переключением runtime production.

Тестовые генераторы документов дополнены отдельно в `testtools/python-fixtures`: python-docx 1.2.0, python-pptx 1.0.2, reportlab 4.4.4, lxml 6.1.3, xlsxwriter 3.3.4 и charset-normalizer 3.5.3. Версии взяты из candidate requirements/constraints, wheel SHA256 сохранены в `context/python-fixtures-manifest.json`. Оригинальный shared runtime не менялся. `PYTHONPATH` содержит этот каталог и `testtools/python` с Playwright; `TMPDIR` отдельный, provider keys и provider key directory не заданы. После добавления зависимостей синтетический media authorization/recovery audit прошёл 11/11.

### Воспроизведение изолированной миграции на Alisa

Рабочий каталог: `/opt/podmasterye/candidates/functionality-transfer-v31/source-r3/products/harness-platform`. `--output` должен указывать на новый, ещё не существующий каталог. Исходный sanitized baseline остаётся неизменным.

```bash
env -i PATH=/usr/bin:/bin:/usr/local/bin PYTHONDONTWRITEBYTECODE=1 \
/opt/harness-prod/runtime/attachments-06f257269dd3/venv/bin/python \
  scripts/verify_transfer_copy.py verify \
  --baseline /opt/podmasterye/candidates/functionality-transfer-v31/finance-migration/sanitized-baseline \
  --output /opt/podmasterye/candidates/functionality-transfer-v31/finance-migration/verified-new-run \
  --node-modules /opt/harness-prod/runtime/attachments-06f257269dd3/node_modules
```

Команда не запускает app lifespan, фоновые таймеры, Telegram или обращения к провайдерам. Она выполняет те же versioned initializer и только read-only native history. Внешние ключи не наследуются; runtime dependencies используются без изменения. Скрипт дополнительно удаляет переменные окружения HARNESS/PODMASTERYE/YOOKASSA/DEEPSEEK/OPENROUTER/TELEGRAM перед собственными действиями.

## Границы доказательств и выпуска

- В финансовых unit/browser сценариях суммы и квитанции синтетические; копия миграции сохраняет реальные финансовые значения, скрытые в публикационных метаданных. Эти сценарии не выполняли платных вызовов. Production DB, balances, ключи, настройки платежей и webhook не изменялись. Изолированные test dependencies не меняют shared runtime или production-сервис.
- В рамках финансовой приёмки этого агента реальный YooKassa purchase/refund и платные вызовы DeepSeek/OpenRouter не выполнялись. Отдельные разрешённые live smoke tests координатора документируются в общем отчёте; их результат не следует из unit/browser тестов.
- Chromium158 подтверждён; Opera и реальное пользовательское окружение являются отдельной общей проверкой выпуска.
- Миграция проверена и на непустых синтетических состояниях, созданных настоящим frozen source, и на согласованной обезличенной копии живых четырёх БД с повторным открытием и restore. Реальный source не содержит оплат/возвратов/незавершённых попыток/вложений/старых таймеров и хозяйственных строк; сохранение непустых состояний этих типов доказывается отдельными синтетическими сценариями, а не пустыми production таблицами.
- Физическое удаление финансовой истории не реализовано. Политика хранения, обезличивания и необратимого удаления требует отдельного согласованного решения; текущий lifecycle изолирует неактивный аккаунт с сохранением финансовых фактов.
- Универсальная ручная сверка не распространяется на неизвестные service tariffs. Такой случай остаётся неизвестным до принятого provider adapter и доказательства; прямого произвольного изменения баланса из формы нет.
- Перед итоговым релизом координатор собирает общие native/browser/regression результаты и commit, проверяет отсутствие секретов/БД/runtime в архиве. Этот агент не коммитил общий tree и не выполнял deploy.
