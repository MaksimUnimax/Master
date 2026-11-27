# Мастерская v31: сервисные контракты

## Общие правила

Большинство JSON API используют существующую cookie/Bearer авторизацию.
Профильная безопасность, смена пароля и browser Telegram connect сохраняют
свой cookie-only транспорт; Bearer не заменяет cookie на этих маршрутах.
Cookie-запросы с эффектом проверяют Origin/CSRF. Сервер разрешает аккаунт и мастерскую сам;
`actor_id` нельзя подставить в параметры пользовательской операции. Метаданные
таймера, файлов и учёта дополнительно привязаны к разрешённому основному чату.

Ответы private API не кэшируются. Ошибки: 400 — неверная форма аргументов,
401 — отсутствующий/отозванный сеанс, 403 — нет роли/допуска, 404 — недоступный
в данной области объект, 409 — конфликт версии или повтор с другими
параметрами. Ошибка провайдера не является разрешением повторно списать деньги.

Денежные величины — точные десятичные строки, внутренний `units` — целое число
долей монеты. Значение `null` в себестоимости означает неизвестную стоимость.
Не преобразовывать его в ноль. При неизвестной стоимости `costComplete=false`,
общий `providerRub=null`, а подтверждённая часть возвращается отдельно в
`knownProviderRub`. При неизвестной USD-стоимости аналогично разделены
`providerUsd` и `knownProviderUsd`. Подтверждённый subtotal нельзя показывать
как полный итог. Баланс и резерв в UI округляются до сотых;
история и API сохраняют точность.

## Аккаунт и кошелёк

| Метод и путь | Контракт |
| --- | --- |
| `GET /api/profile` | Собственный login, admin, известная дата регистрации; неизвестная дата не выдумывается |
| `GET /api/profile/security` | Browser cookie; подтверждённая почта и политика дополнительного входа |
| `POST /api/profile/security` | Browser cookie + same Origin; URL-encoded form `current`, `enabled`, штатное подтверждение; защита администратора обязательна |
| `POST /api/profile/password` | Browser cookie + same Origin; URL-encoded form `current`, `password`, `confirmation`; штатная ротация и отзыв сеансов |
| `GET /api/profile/sessions` | Непрозрачный ID сеанса, текущий сеанс, время/срок при наличии; токены не возвращаются |
| `POST /api/profile/sessions` | `action=revoke` + `sessionId` либо `action=others`; отзывает связанный допуск |
| `GET /api/wallet` | Точный общий кошелёк и сведения учёта |
| `GET /api/wallet/balance` | Краткие available/reserved; используется общим refresh controller |
| `GET /api/wallet/history` | Фильтр вида операции и серверная пагинация; начисления, покупки, возвраты, попытки и резервы |
| `POST /api/account/integrations/resume` | `channel=telegram` или `marketplace`; только владелец активного аккаунта |

Смена пароля сохраняет существующий серверный обработчик и обязательную
проверку текущего пароля. Не добавлен параллельный endpoint авторизации.

## Учёт, помощник и встроенные возможности

Фактические схемы хранятся в `capability_registry.schema(id)`, а bindings —
в `capability_registry.BINDINGS[id]`. `describe(db, scope)` возвращает разрешённые
возможности и их `entrypoint`/`transport`. Это описания уже существующих
обработчиков, а не отдельный универсальный endpoint, которому разрешён
произвольный вызов Python-функции.

`podmasterye_book.preview_action(db, workshop, operation, arguments)` возвращает
нормализованные параметры и версию данных. Подтверждение проходит через
`commit_action(db, workshop, request_id, operation, arguments, revision)`.
Тот же receipt проверяется при сетевом повторе до сравнения версии текущих
остатков: повтор собственной уже выполненной записи не падает из-за того,
что сама запись изменила остатки. Другие аргументы с прежним ID отклоняются.

| Метод и путь | Контракт |
| --- | --- |
| `GET /api/model-settings` | Доступный пользователю выбор прямой/OR-модели и состояние каталога |
| `POST /api/model-settings` | Существующий контракт выбора модели; тариф и совместимость проверяет сервер |
| `GET/POST /api/assistant/preferences` | `address`, `tone`, `detail`, `revision`; полная допустимая форма возвращается сервером |
| `GET/POST /api/assistant/illustrations/settings` | Модель иллюстраций и `revision`; подтверждение изменившегося бесплатного тарифа |
| `GET /api/chats/{chat_id}/illustrations` | История созданных изображений в области владельца |
| `GET /api/chats/{chat_id}/illustrations/{id}` | Скачивание разрешённого сохранённого изображения |
| `POST /api/chats/{chat_id}/turns` | `requestId`, `text`, при необходимости `maxCoins`, attachments и разрешённый view/form context |

Исторический `/api/octopus/preferences` — алиас **того же** handler и таблицы
`octopus_preferences`. Он сохраняет совместимость старых клиентов и не создаёт
второй профиль. Условие удаления алиаса — прекращение поддержки клиентов,
обращающихся к старому URL; новые UI используют `/api/assistant/preferences`.

## Расписания

Префикс владельца: `/api/chats/{chat_id}/timer`. Определение события содержит
тип, разрешённый шаблон отчёта/операции, параметры, timezone, правило времени и
каналы. Shell, SQL, произвольный URL и токен сессии не являются полями события.

| Метод | Суффикс | Эффект |
| --- | --- | --- |
| GET | пустой | События, действующие черновики, шаблоны, состояние общей Telegram-привязки |
| POST | `/preview` | `requestId`, `definition`, для правки `eventId`+`revision`; без создания события |
| POST | `/confirm` | `requestId`, `draftId`, `revision`, `receipt`; сохранение проверенного определения |
| POST | `/events/{event}` | `requestId`, `operation=pause/resume/cancel/run`, `revision` |
| GET | `/events/{event}/history` | Постраничные исполнения и независимые статусы доставки |
| POST | `/drafts/{draft}/cancel` | `requestId`, `revision`; отзыв непринятого предпросмотра |
| POST | `/runs/{run}/confirm` | Подтверждение актуального предпросмотра конкретного хозяйственного действия |
| POST | `/runs/{run}/retry` | Повтор допустимой доставки; unknown не повторяется вслепую |
| GET | `/runs/{run}/report.json` | Полный сохранённый локальный результат |

Отчёт сохраняется один раз. Native публикация имеет ID запуска; Telegram
имеет свой receipt. Повтор доставки не вызывает повторное изменение учёта.
Просроченное/отозванное подтверждение даёт 409, не 500.

## Административные контракты

| Метод и путь | Защищённая операция |
| --- | --- |
| `GET /api/admin/finance` | Период, аккаунт, поставщик/вид, точные подтверждённые суммы и неизвестные исходы |
| `POST /api/admin/finance/reconcile` | `attemptId`, `version`, `amount`, `currency`, `reference`; квитанция и атомарный аудит |
| `GET /api/admin/payments` | Существующие checkout, фильтры, пагинация, отдельное безопасное состояние own merchant configuration |
| `POST /api/admin/payments/reconcile` | `checkoutId`, `version`; GET-проверка существующего платежа у ЮKassa, затем общий apply_payment |
| `POST /api/admin/accounts/preview` | Список `actors`, `action`; зависимости, баланс, файлы, ограничения и fingerprint |
| `POST /api/admin/accounts/lifecycle` | `requestId`, `items=[{actor,expected}]`, `action`, `reason`; отдельный savepoint каждого аккаунта |
| `GET /api/admin/provider-keys` | Только configured/enabled/health, без значения ключа |
| `POST /api/admin/provider-keys/{provider}` | Write-only ключ поддерживаемого провайдера |
| `GET/POST /api/admin/ai-models` | Актуальный каталог и допуск модели с revision |
| `GET/POST /api/admin/chat-default` | Общая модель по умолчанию и reasoning |
| `GET /api/admin/provider-balances` | Состояние независимых балансов, порогов и общей привязки уведомлений |
| `POST /api/admin/provider-balances/{action}` | Штатные refresh/settings/alert-settings/telegram-test |
| `POST /api/admin/provider-balances/telegram-connect` | Штатный browser-cookie-only connect через `telegram_integration`; не отдельная Telegram-привязка |
| `GET /api/admin/timer` | Метаданные событий, ошибки, пагинация 10/20/50/100; без текста чужого отчёта |
| `POST /api/admin/timer/pause` | `requestId`, `eventId`, `revision`; отзыв старых запусков и audit |
| `GET/POST /api/admin/analytics` | Состояние собственного счётчика; `enabled`+`revision` для включения/отключения |
| `GET /api/admin/system` | Фактическая read-only конфигурация origin, почты, оплаты, аналитики, таймера и миграций |

`action=delete` возвращает проверяемый предпросмотр, но не выполняется:
политика хранения и отдельная приёмка не утверждены. UI не показывает доступное
подтверждение удаления. Никакой новый маршрут необратимого удаления не открыт.

Платёжная сверка не создаёт новый платёж и не доверяет сумме браузера. Реальная
активация checkout остаётся во внешней конфигурации и требует отдельного допуска.

## Публичная аналитика

`GET /api/analytics/config` возвращает только `enabled=false` или разрешённые
`counter`/`origin` при совпадении hostname с общей конфигурацией. Секретный токен
отчётов не возвращается. Cookie consent, настройки privacy и публичные
SPA-переходы обслуживает один `analytics.js`. Страницы входа, регистрации,
админки и личного кабинета исключены.
