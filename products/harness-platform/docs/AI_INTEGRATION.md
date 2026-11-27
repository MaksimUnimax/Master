# Встроенный помощник Мастерской: контракт интеграции

Дата: 27.11.2026. Область: AI01–AI08 ТЗ-ПФ-001. Этот документ описывает
поддерживаемые исходники и точки подключения. Наличие реализации или прохождение
локального стенда не является приёмкой реального провайдера.

## Один путь выполнения

Авторизованный HTTP-ход проходит через `podmasterye_scoped.routes`,
`podmasterye_domain.decide`, штатный `ChatWorker` и native Harness. Локальный
калькулятор/FAQ/учётный маршрут сохраняет существующую детерминированную ветку.
После модельного хода хозяйственные изменения проводит серверный finalizer
Мастерской с текущим разрешением записи и актуальной версией предметных данных.
Модельный текст сам по себе не является согласием пользователя.

`capability_registry` описывает встроенные `assistant.chat`, `assistant.web`,
`assistant.illustration`, `assistant.preferences`. `permitted(db, scope, id)`
проверяет владельца аккаунта, состояние жизненного цикла, чат и архив мастерской.
Для аккаунтных настроек используется `OperationScope(actor_id, workspace_id)`;
для чата — `Scope(actor_id, workspace_id, chat_id)`. Тип `storage.Scope` требует
непустой `chat_id`. Внешний транспорт дополнительно проверяет scoped grant,
сессию и финансовую резервацию перед каждой отправкой.

Реестр не вводит фиксированную минимальную сумму. Бесплатная модель OpenRouter
сохраняет доступ к тем же разрешённым локальным MCP-инструментам при нулевом
балансе. Платная генерация, Search/Fetch и изображения требуют собственного
подтверждённого тарифа и резерва общего денежного журнала.

## Запуск приложения и маршруты

Инициализация должна быть выполнена независимо от включения OpenRouter:

```python
with identity._write() as db:
    ai_settings.initialize(db)

router = await stack.enter_async_context(model_router.activate(
    identity, http, worker,
    allow_illustrations=True,
    recovery_policy=ai_settings.WorkshopRecoveryPolicy(app.state),
))
ai_settings.configure_router(app.state, router)
```

Recovery policy передаётся при создании router **до** старта фоновой recovery
task. Последующий `configure_router` сохраняется как общий hook, но не заменяет
этой границы. При восстановлении опубликованный результат проходит
`podmasterye_domain.complete_from_session`: проверяется исходная сессия,
владелец, жизненный цикл и область мастерской.

| Контракт | Назначение |
|---|---|
| `GET/POST /api/model-settings` | Аккаунтный выбор модели, default/direct, revision глобальной политики |
| `GET /api/admin/chat-models` | Доступные чату модели и режимы рассуждения |
| `GET/POST /api/admin/chat-default` | Общая модель, источник и поддерживаемый effort |
| `GET/POST /api/admin/ai-models` | Разрешение модели администратором, CAS revision, диагностика совместимости |
| `GET /api/admin/provider-keys` | Только факт настройки и диагностическое состояние |
| `POST /api/admin/provider-keys/{provider}` | Сохранение/замена отдельного ключа DeepSeek или OpenRouter |
| `GET/POST /api/assistant/preferences` | Обращение, тон, подробность, CAS revision |
| `GET/POST /api/octopus/preferences` | Временный URL-алиас к тому же хранилищу предпочтений |
| `GET/POST /api/assistant/illustrations/settings` | Аккаунтная модель встроенной генерации, отдельная revision |
| `GET /api/chats/{chat_id}/illustrations` | История версий с limit/offset и nextOffset |
| `GET /api/chats/{chat_id}/illustrations/{id}` | Скачивание артефакта владельцем |
| `GET/POST /api/assistant/permissions` | Текущий режим подтверждения хозяйственных изменений v30 |

Мониторинг балансов использует `provider_balances.routes`. Его `BalanceMonitor`
создаёт `provider_balance_alerts.BalanceAlerts` с общей `TelegramIntegration`;
у `provider_balance_alerts` нет отдельного route hook. Штатную привязку
администратора, включая `/api/admin/provider-balances/telegram-connect`,
монтирует `telegram_integration.routes`. Второго опросчика, scheduler или
денежного журнала нет.

Регистрация в `chat_api.create_app`:

- `assistant_preferences.routes(token_for, body)`;
- `ai_settings.routes(token_for, body)`;
- `model_router.routes(token_for, body)` даже при `model_router is None`;
- `illustrations.routes(token_for)`;
- `provider_keys.routes`, `provider_balances.routes`, `telegram_integration.routes`;
- существующие scoped, progress, attachment и native-document маршруты.

## Провайдеры, цена и совместимость

DeepSeek остаётся прямым рабочим маршрутом. Проверка наличия его ключа выполняется
после определения модели текущей операции: выбранный OpenRouter не зависит от
ключа DeepSeek. Реальная работа OR требует включённой конфигурации, ключа и
настроенного `OPENROUTER_PROXY_URL`; отсутствие обязательного proxy не вызывает
неявный прямой HTTP-egress.

Каталог поставщика — реклама возможностей, а не доказательство их работы в
Harness. `ai_model_compatibility` хранит отдельные результаты валидации по
назначению. Для чата обязательны tools, streaming, context, cancel; для
изображений — image, artifact, billing. `record_compatibility` — серверный
validation hook с обязательной ссылкой на evidence, не browser API. Нельзя
заполнять production evidence результатом теста с MockTransport.

`ai_settings.decorate` пересекает advertised capabilities, подтверждённую
совместимость и серверное разрешение администратора. Неизвестная OR-модель видна
в административной диагностике, но не предлагается пользователю как проверенная.
Рабочие прямые модели DS сохраняют совместимость существующего adapter; live
acceptance текущего кандидата всё равно документируется отдельно.

Администратор выбирает источник `deepseek`, `openrouter-paid` или
`openrouter-free`. Сохранение проверяет текущий тариф. Когда ранее бесплатный
тариф становится платным, сервер требует нового выбора; автоматического платного
fallback нет. Модель и effort, цена и лимиты контекста фиксируются при выдаче
operation grant. Уже начатая операция сохраняет снимок после смены общей модели,
личного выбора или административного разрешения. Аккаунт/сессия могут быть
отозваны в любой момент и всегда проверяются заново.

Глобальное `model_choices.publish` увеличивает revision. Старый личный выбор с
предыдущей revision перестаёт действовать; пользователь наследует новую общую
политику и может снова сохранить личный выбор. `default` явно удаляет личный
override. Старый direct operation сохраняет свой маршрут даже после включения OR.

Стоимость, резервы, квитанции, reconciliation и неизвестные исходы используют
`usage_operations`, `coin_orders`, `coin_attempts`, `coin_ruble_orders` и общий
`finance_reporting`. Доли монеты хранятся целыми числами 10^12. При неизвестном
внешнем исходе повторная отправка запрещена до штатной сверки. При подтверждённом
429 повтор использует ту же попытку и сохраняет Retry-After и серверный снимок.

## Предпочтения и v30

`assistant_preferences.py` использует существующую единственную таблицу
`octopus_preferences`. Значения ограничены enum:

- обращение: «на вы», «на ты»;
- тон: «дружелюбно», «по-деловому»;
- подробность: «по существу», «кратко», «подробно».

Native `assistant-preferences.mjs` добавляет эти значения к инструкции каждого
адаптера; произвольный системный текст из формы не принимается. Checkpoint
сохраняет предпочтения операции. Они не меняют schema инструментов, права,
правила расчёта или подтверждения.

Из актуальной Мастерской v30 перенесены `workshop_write_permissions`,
`workshop_web_topics`, native контекст разрешений и серверные квитанции после
автоматического сохранения. Recovery получает режим записи по существующему
requestId, а не доверяет старому модельному сообщению. Публичные web-данные не
могут изменить режим записи.

## Интернет и изображения

`web_access.WebAccess` и native `mountWeb` — существующий механизм DeepSeek
Search/Fetch. В Мастерской включён natural public-clause planner v30. Перед
egress проверяются scoped grant, registry, аккаунт, архив, paid access, тариф,
публичный план, приватные значения и публичность URL/DNS. Исходная приватная
реплика не отправляется целиком в поиск. Внешний текст помечен недоверенным;
произвольные операции из страницы не исполняются. Режимы «быстрый/глубокий поиск»
не добавлены: для них ещё нет отдельного сравнительного доказательства стоимости
и совместимости.

Встроенный `create_illustration` использует один engine
`user_plugins/illustrations.py`. Legacy имя файла и таблица `plugin_illustrations`
не означают требование установки плагина. Единственный UI/model setting —
`capability_model_settings`; снимок хранится в `operation_capability_models`.
Prompt hash предотвращает подмену повторного requestId. До отправки резервируется
точная верхняя цена из тарифного снимка. Готовый артефакт повторно возвращается
без вызова поставщика, включая временную недоступность провайдера. Неизвестный
результат не генерируется заново.

Артефакты привязаны к чату/операции и имеют неизменяемую версию. Разрешены
PNG/JPEG/WebP; ответы не кешируются и содержат nosniff. HTTP-скачивание проверяет
владельца и жизненный цикл. Изображение связано с основным сообщением через
existing presentation projection и `PMAI.message`.

Native document/file/audio контур не заменён. Сохраняются существующие
XLSX/DOCX/PPTX/PDF/CSV/TXT/JSON/ZIP инструменты и финансовые границы. Штатные
таймерные сообщения используют общий native journal; второй history store нет.
Гостевой контур не монтирует эти возможности: собственная матрица, готовые ответы,
classifier-only DeepSeek Flash и отсутствие новых квот сохраняются.

## Авторизация при архивировании и восстановлении

Registry проверяется на входе в turn и web dispatch. Общий operation grant
дополнительно проверяет текущее состояние workshop/account/chat при выдаче,
использовании и продлении. Native gateway resolver повторяет эту проверку до
обращения к провайдеру; optional product tables обнаруживаются динамически,
поскольку процесс gateway может стартовать до миграций приложения. На общем
Harness без product tables совместимость сохраняется; частичная product schema
закрывает доступ.

Архивирование мастерской отзывает её существующие grants и расписания в той же
транзакции. Восстановление не активирует старые tokens или timer runs. Unknown
provider attempts сохраняются для штатной финансовой сверки, без повторного
dispatch. Проверки находятся в `tests/test_transfer_ai_authority.py` и общей
gateway regression. Гостевая регистрация с retry/restart/context проверяется
реальным native Harness в исходном test ID `test_native_retry_and_restart_preserve_messages_and_context`.

В проекции общей истории обычный user turn сохраняется и при пустом тексте:
так отправляются сообщения только с файлом, а вложения добавляет native history
enrichment. User row отсутствует только у server-owned exchange с `system=true`,
например сообщения таймера. Префикс requestId и пустой текст не являются таким
признаком. Регрессия `test_transfer_ai_history` проверяет enrichment, повтор,
повторное открытие БД и смешанную историю обычного сообщения с таймером.

## UI hooks

`podmasterye-ai-settings.html`, `pm-admin-ai-models.html`,
`pm-admin-ai-keys.html`, `pm-admin-ai-balances.html` подключаются основной
web-композицией. Единственные дополнительные assets — `podmasterye-ai.js` и
`podmasterye-ai.css`. `window.PMAI.mount()` монтирует формы; повторный вызов
безопасен. `window.PMAI.message(parent, message)` добавляет разрешённый локальный
артефакт в общий renderer. Сохранённые ключи не читаются и поле очищается после
успеха. Тарифы вычисляет сервер; браузер показывает полученные ограничения.

## Миграции и обратная совместимость

| Версия | Изменения |
|---|---|
| `20261127_ai_v1` | Общие prefs/model schema, admin permissions, compatibility evidence, builtin model settings, operation snapshots, balance thresholds, prompt hashes, existing illustration storage |
| `20261127_ai_v2` | Неизменяемая `illustration_versions`, однократный backfill существующих артефактов |
| `20261127_permissions_v30` | Существующие v30 `pm_write_preferences`, `pm_write_intents` через общий migration runner |

Все используют `schema_migrations.apply` с SAVEPOINT/checksum. Миграция не
пересчитывает и не переносит деньги в другой журнал. Повторная инициализация
сохраняет суммы и настройки. URL `/api/octopus/preferences` может быть удалён
после исчезновения старых клиентов; хранения/писателя у него своего нет.

## Проверки и граница приёмки

Активный Python runner вновь включает `test_openrouter_catalog`,
`test_openrouter_operations`, `test_openrouter_recovery`: удалены устаревшие
exclusions «OpenRouter disabled». Все 35 upstream сценариев сохранены. Адаптация
меняет fixture setup: builtin image settings вместо plugin installation,
Workshop `/messages` вместо Octoport `/events`, отдельное fixture compatibility
evidence и обязательный recheck тарифа при сохранении. Финансовые assertions,
проверки остановки, реального kill/restart и запрета replay не ослаблены.

Дополнительное покрытие: `test_transfer_ai`, `test_transfer_ai_http`,
`test_shared_web_access`, `test_workshop_permissions_v30`, native preference,
OpenRouter, compaction, transfer-contract и capability-filter tests, browser
`test_transfer_ai_ui`. HTTP-тесты используют настоящий native Harness и MCP,
но локальный MockTransport поставщика. Они не сертифицируют real model IDs.

`acceptance/ai_live_acceptance.py` по умолчанию только пишет инвентаризацию
runtime исходников без сети. Для исполнения нужны exact approved source digest,
PID отдельно запущенного кандидата, его БД, отдельный `ai_acceptance_` аккаунт,
собственный чат и local session file 0600. Script обращается только к loopback
HTTP API этого процесса. БД открывается read-only. Перед каждым новым ходом
проверяются source hash, процесс и остаток общего бюджета не более 5 ₽.

Живой сценарий содержит три коротких хода: DS, Search, Fetch. Каждый использует
`maxCoins` общего ledger; каждый replay проверяется по отсутствию новых попыток.
Unknown/pending расход останавливает следующие ходы. Существующая резервация
остаётся для штатной сверки. Script не выдаёт монеты, не создаёт пользователей,
не устанавливает ключи и не вызывает OR generation. Необязательный admin session
читает только configured/enabled OR status. Этот сценарий сам по себе не является
приёмкой всех OR моделей, мультимодальности или отдельного deep-search режима.

Exact runtime digest сценария дополняет общий release manifest; не заменяет его.
Перед переносом/запуском требуется пересоздать inventory на окончательном
кандидате и сверить оба manifest. Не следует запускать этот сценарий против
рабочего пользовательского чата или подменять provider gateway тестовым.
