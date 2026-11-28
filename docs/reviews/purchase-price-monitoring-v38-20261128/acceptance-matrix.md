# Итоговая матрица приёмки

Кандидат: `c33a108e036feb4487ee4f3a247abca8e1950313`.

Статусы: PASS 30, FAIL 0, BLOCKED 28, NOT_RUN 0. Полная приёмка релиза не дана.

Редакция отчётности r2: код, первичные журналы и исходы тестов не изменены. Пути `evidence/…` ниже обозначают файлы закрытого ZIP; в публичном GitHub они приведены как идентификаторы доказательств, а не открытые ссылки. Окончательный архив связывает внешний `DELIVERY_MANIFEST.json`. GitHub-публикация и передача владельцу фиксируются отдельно после выполнения.

| ID | Статус | Исходный критерий | Подтверждённая область и ограничение |
|---|---|---|---|
| MC-01 | PASS | Все операции зарегистрированы в одном типизированном реестре; действующие handlers, схемы, роли, error_policy, progress_policy, тесты. | Проверены 15 действующих handlers, строгие входные и выходные JSON schemas, scope/роли/эффекты/подтверждения/error/progress. Исполняемый execute валидирует и обычный ответ, и повтор по request ID. |
| MC-02 | PASS | UI и чат дают одинаковые параметры, ID, результаты, состояние, подтверждения и квитанции через один авторитетный путь; DUAL-01–08. | Обе поверхности используют один execute и общие ID/версии/состояние/квитанции. Подтверждены пользовательские параметры, фильтры и результаты; граница служебной CSV-пагинации явно описана в notes. |
| MC-03 | PASS | Полный независимый цикл UI и чата, включая уточнение/возобновление/удаление; точные команды без разговорного LLM; локальный UI работает при выключенном DeepSeek и нуле монет. | Исполнены независимые полные cabinet-only и chat-only циклы. Exact chat команды идут локально без разговорного LLM; локальные операции доступны без монет, платная проверка при нехватке резерва отклоняется до сети. |
| MC-04 | PASS | Таймер, лимитер, уведомления, биллинг переиспользованы; нет дублирующей архитектуры/cron/кошелька; ревью исходников. | Ревью текущих исходников подтверждает общий timer/jobs/store, parser orders/limiter, service billing/ledger и штатную доставку. Предметные таблицы хранят мониторинг и ссылки на общие попытки; второго кошелька или cron нет. |
| MC-05 | PASS | Гость/чужой пользователь не получают доступ к функциям, данным или платному запуску; изоляция мастерских и ролей. | Проверены guest/foreign scope, разные пользователи/мастерские, текущая роль и отзыв разрешения. Браузерные проверки и реальные scoped HTTP/domain операции не предоставляют чужих данных или платного допуска. |
| MC-06 | PASS | Ввод только ссылки, автоназвание, редактирование; безопасная валидация и дедупликация точной позиции. | Базовый экран принимает URL; необязательное название спрятано в дополнительном блоке. Автоназвание, ручное переименование 240 Unicode code points, каноническая дедупликация и безопасный URL проверены. |
| MC-07 | PASS | Маршрутизация Ozon/WB/YM и прочих доменов без LLM, исключена подмена похожим доменом/товаром. | Один детерминированный classify направляет точные карточки Ozon/WB/YM и прочие публичные домены. Проверены похожие хосты, идентичность товара, варианты и запрещённые адреса; модель для маршрутизации не вызывается. |
| MC-08 | BLOCKED | Контракт parser.market Ozon, фактическая цена и единицы подтверждены; нет LLM/поиска/отзывов. | Контролируемые adapter/request/receipt и shared scheduler случаи подтверждают реализацию Ozon exact-card пути. Живые цены, квоты и квитанции требуемой выборки Ozon отсутствуют. |
| MC-09 | BLOCKED | Аналогично WB, включая необходимые поля типа цены, региона и варианта. | Контролируемые случаи проверяют WB-карточку, вариант/размер, регион, смысл цены и отказ несогласованных данных. Живое подтверждение требуемой выборки WB отсутствует. |
| MC-10 | BLOCKED | Аналогично YM, включая подтверждённое региональное ограничение. | Контролируемые случаи проверяют YM exact-card/SKU и московское региональное ограничение. Живое подтверждение нужных полей, цены и единиц YM отсутствует. |
| MC-11 | PASS | parser.market общие тарифы/резерв, исходный ID заказа, poll/download, точная квитанция и отсутствие двойного списания. | Реальный общий reserve/order/poll/download/settlement путь приложения исполнен с контролируемым поставщиком. Исходный ID и pinned pricing сохраняются; повтор не создаёт второе списание, неполная квитанция не оценивается как ноль. |
| MC-12 | PASS | Выбор неоднозначного структурированного предложения маркетплейса через общий локальный механизм уточнения; 0 LLM для точного выбора. | Реальное структурированное предложение проходит общий вопрос и точный выбор стабильного basis ID. Условия упаковки/акции/промокода видимы; числовая цена в выборе не закрепляется; LLM для выбора не нужен. |
| MC-13 | BLOCKED | Read URL встроен в общий безопасный шлюз/учёт; верные служебные блоки и usage; другие чатовые маршруты без регрессии. | Production grant безопасно останавливает недопущенный ReadURL до ключа/кошелька/upstream; остальные маршруты проверены полной регрессией. Платная ReadURL-композиция dispatch/tool-result/usage/settlement ещё не реализована. |
| MC-14 | BLOCKED | Настройка: однозначная публичная цена, автоназвание и индивидуальное краткое правило сохраняются без лишних вопросов. | Компактное сохранение названия/цены/индивидуального правила проверено на domain и чистом валидаторе. Рабочая первоначальная настройка обычного сайта через ReadURL не исполнена. |
| MC-15 | BLOCKED | Регулярный запрос: URL + название + минимальное согласованное правило, Flash без рассуждений/истории/Search; обычный успех — одно чтение. | Чистый builder проверяет короткие настроечный/рабочий запросы, ограничения history/tools/Flash и границы данных. Это не подтверждение одного фактического оплаченного чтения обычного сайта. |
| MC-16 | BLOCKED | Ответ без подтверждённого tool call или с ошибкой web_fetch_tool_result отвергается даже при HTTP 200; нет выдуманной цены. | Валидатор и domain отвергают HTTP200/текстовую цену без подтверждённого чтения, failed tool result, неполную usage и чужой URL. Валидатор пока не подключён к действующему платному ReadURL-исполнению. |
| MC-17 | BLOCKED | Проверка URL/идентичности/валюты/единицы, строгая схема, точность дробных цен, отсутствие подмены корзиной/рекламой/старой ценой. | Для доступного parser-пути проверены identity/URL/region/basis, строгая 18+18 decimal цена, отсутствие старой/корзинной цены и точный график. Проверка этих условий на действующем ReadURL остаётся незавершённой. |
| MC-18 | PASS | Неоднозначность порождает один привязанный вопрос с реальными вариантами; статус в таблице и штатная публикация в чате. | Одна неоднозначность создаёт один item/version/run-bound вопрос из настоящего ответа контролируемого поставщика. Он публикуется в штатной истории и виден в таблице; переход «Ответить в чате» открывает этот же вопрос. |
| MC-19 | PASS | Ответ из UI или чата обновляет одну версию шаблона, закрывает оба представления; повтор/конкуренция/устаревший ответ без дублей. | Обе поверхности закрывают один вопрос и обновляют одну версию. Проверены stale/replay/конкуренция, точные 600 code points свободного ответа и отсутствие второй независимой задачи. |
| MC-20 | BLOCKED | Уточнение запускает новую проверку по краткому правилу; без ответа платных циклов нет; нехватка средств не теряет выбор. | Общий вопрос блокирует новые проверки; выбор переживает финансовую паузу и вызывает следующий parser-check. Проверка обычного сайта по уточнённому короткому ReadURL-правилу пока отсутствует. |
| MC-21 | BLOCKED | Изменение структуры — контролируемая перенастройка; изменение смысловой цены — уточнение/новая серия, без ложного сигнала. | Domain отличает смену locator от смены смысла цены и создаёт подтверждённую новую серию без ложного сравнения. Фактическая перестройка обычной страницы через ReadURL не исполнена. |
| MC-22 | BLOCKED | CAPTCHA пропускает наблюдение до следующего срока, старые данные не изменены, нет обхода/быстрого цикла. | Domain сохраняет последнюю цену и очередной срок при CAPTCHA; чистый helper отличает подтверждённую challenge-страницу от failed tool receipt. Реальная ReadURL CAPTCHA-стадия не проверена. |
| MC-23 | BLOCKED | Обязательная авторизация недоступна, проверка остановлена; нет хранения учётных данных или сессий. | Domain останавливает конкретный auth-required товар без cookies; helper принимает статус только из подтверждённого результата. Действующий ReadURL login-wall путь отсутствует. |
| MC-24 | BLOCKED | Нет товара/цены, недоступность, блокировка, 404/410, неопределённость отличимы; нет фиктивного нуля или ложного успеха. | Доступный parser-путь различает отсутствие цены/товара, ошибки, unknown и retry, сохраняет последнее подтверждённое наблюдение и не пишет нули. Полный набор обычных ReadURL-исходов не исполнен. |
| MC-25 | BLOCKED | 429 на каждой сетевой стадии, три подряд и постоянный отказ; правильные Retry-After, backoff, сохранённый checkpoint и освобождённый worker. | Actual parser transport проверен по balance/send/poll/download, четырём видам Retry-After, трём подряд и постоянным 429; cooldown/checkpoint освобождает worker и не дублирует резерв. ReadURL network stages отсутствуют. |
| MC-26 | BLOCKED | 400/401/403/422/5xx/timeout/TLS/ошибка схемы: типизированное безопасное действие; без слепых повторов и обхода доступа. | Actual parser matrix проверяет permanent/transient HTTP, TLS, timeout/reset, schema/receipt ошибки и безопасное продолжение исходного заказа. Такая матрица на действующем ReadURL пока невозможна. |
| MC-27 | BLOCKED | Неизвестный платный исход не пересылается до сверки; резерв и исходные IDs сохранены; расход не выдан за ноль. | Actual parser unknown acceptance сохраняет исходные order/attempt/hold через restart/cancel, сверяется с исходной квитанцией и корректно принимает capped settlement без повторной покупки. Paid ReadURL unknown usage/settlement ветвь отсутствует. |
| MC-28 | PASS | Настройка расписания/критериев/каналов, ручная проверка, пауза, остановка, возобновление и удаление через штатный timer. | Проверены все расписания и пользовательские параметры, критерии/каналы, manual/start/pause/resume/stop/delete на общем timer. Разовое событие корректно завершает item без отзыва финальной доставки; просроченный once не запускается заново без будущего расписания. |
| MC-29 | PASS | Фоновые задачи без вкладки/чата, устойчивый допуск без старой cookie, права/версия/отмена перед отправкой; рестарт и missed windows. | Фоновый допуск связан с текущим owner/workshop/item/template/run и конечной lease, без старой browser cookie. Проверены revoke/version/cancel/payload, restart и coalescing missed windows без backfill. |
| MC-30 | PASS | Уникальность occurrence и запроса, перекрытие ручного/планового запуска, конкуренция и lease fencing без дублей. | Проверены request/occurrence uniqueness, manual/scheduled overlap, конкурентные claims и lease fencing. Истёкший допуск откладывает ту же зарезервированную попытку; новая покупка не создаётся. |
| MC-31 | PASS | Все критерии уведомления проверены на точных суммах/процентах/порогах, первая цена и несопоставимые серии не создают ложных сигналов. | Точные Decimal tests закрывают all/change/increase/decrease/amount/percent/threshold crossing, направление, равенства границ, нулевую базу, первую цену и несопоставимые серии. Несколько совпавших правил дают одно логическое уведомление. |
| MC-32 | BLOCKED | Доставка в чат, Telegram, оба канала; единый результат, дедупликация, ошибки/отвязка/unknown доставки; 0 LLM для уведомлений. | Actual monitoring→timer→native chat и контролируемый Telegram sender проверяют оба канала, consent, dedup, unknown и disconnect/reconnect без новой цены и без LLM. Требуемая живая Telegram-проверка не выполнена. |
| MC-33 | BLOCKED | Единый учёт токенов и parser.market, точные версии тарифов/курса, отсутствие двойного счёта server tool и standalone Fetch. | Общий parser ledger и существующие token/server-tool механизмы проверены отдельно. Предметные ReadURL input/cache/output usage и settlement не интегрированы; полный единый учёт этого маршрута не доказан. |
| MC-34 | BLOCKED | Резерв до каждой платной стадии, верхняя граница доказана, точный/недостаточный/достаточный баланс и конкурентные резервы. | Резерв parser-попытки делается до отправки; exact/insufficient/concurrent balance проверки исполнены. Совокупная оплачиваемая ReadURL-граница не доказана, поэтому этот маршрут закрыт до финансового допуска. |
| MC-35 | BLOCKED | Нехватка баланса в ходе активной задачи: неотправленный платный вызов не списан, сохранён прогресс, одно уведомление, восстановление после пополнения без backfill. | Actual wallet/episode проверки сохраняют выбор и прогресс, закрывают завершённый эпизод, не возрождают manual pause/stop и восстанавливают только financial pause. Живая проверка баланса разрешённого аккаунта по§14D отсутствует. |
| MC-36 | BLOCKED | Баланс поставщика/квота отличимы от клиентского баланса, штатное уведомление админа, корректная пауза без лишних расходов. | Отдельный actual monitoring quota proof: реальный reserve>0→supplier balance0→provider pause→settled0/not_dispatched, wallet не меняется, paid sends0, одно штатное admin-уведомление на два товара. Подменены только внешние parser/Telegram transports. ReadURL provider-constraint ветвь отсутствует. |
| MC-37 | BLOCKED | Только admin: таблица показывает себестоимость настройки/уточнений/проверок/ошибок/диагностики, токены, проверки и единый ledger. | Admin table сверена с авторитетным parser API/ledger по полям, страницам и стадиям; неподтверждённые значения обозначены честно. Реальных предметных ReadURL token-cost записей настройки/проверок пока нет. |
| MC-38 | BLOCKED | Только admin: соответствующая техническая детализация под результатом в чате; идентичность записи таблице и админке, без повторного расхода. | Admin technical details в native card используют тот же текущий ledger, сохраняют run/page и повторно проверяют роль без нового расхода. Реальные ReadURL usage/costs через этот предметный путь пока не получены. |
| MC-39 | PASS | Обычный пользователь и гость: 0 утечек админских расходов через UI, DOM, API, stream, историю, экспорт и инструменты модели; проверка смены роли. Штатный кошелёк сохранён. | API, model/native projection, сохранённые turns, CSV/history и оба браузера проверены на отсутствие расходов у member/guest. Downgrade и задержанный старый 200 не восстанавливают private DOM благодаря общей epoch и render fence; штатный wallet сохранён. |
| MC-40 | PASS | Компактные метаданные и история: без хранения полного тела страниц, фото, отзывов/рассуждений; индексы, пагинация, измеренный размер. | Сохраняются компактные шаблоны/условия/наблюдения, без полного HTML/media/reasoning. Измерены 365000 наблюдений 1000 товаров,50 samples/read, индексы/пагинация/размер/RSS/latency; все 14 заранее заданных проверок выполнены. |
| MC-41 | PASS | Графики/сводки/история точны, временные пропуски не нули; локальный доступ при недоступном провайдере; 0 модельных/сетевых вызовов для расчёта. | Точная история/агрегаты/фильтры/CSV локальны и доступны без поставщика. Actual browser graph различает 18-decimal цены, которые совпадают в Number; временные пропуски и разные серии не превращаются в нули. |
| MC-42 | PASS | Пауза хранит историю, удаление с подтверждением останавливает задачи и очищает предметные данные по политике; финансовый аудит сохранён. | Pause/stop сохраняют историю; delete требует current version+confirm, прекращает задачи и очищает предметные данные. Идемпотентный tombstone не возвращает удалённые данные, финансовые квитанции и исходная сверка сохраняются. |
| MC-43 | BLOCKED | SSRF, URL, редиректы, инъекции сайта, ограниченный tool scope, секреты и неподтверждённые цены; ноль утечек/мутаций поставщика. | Локальные SSRF/URL/identity/scope/secret/injection guards и закрытый gateway проверены. Принудительное ограничение редиректов и tool scope действующего внешнего ReadURL не доказано; чистый prompt не считается таким доказательством. |
| MC-44 | PASS | Стресс: 100 одновременных запросов и 1000 повторов одной операции, одна логическая задача, ноль дублей. | Фактический stress prelude:100 одновременно и 1000 повторов одногоrequest ID дали одну логическую попытку и одно наблюдение, без повторной покупки/публикации. |
| MC-45 | BLOCKED | Стресс: >=1000 событий на адаптер и >=20 клиентов, общие квоты/изоляция; серийные и случайные ошибки без повреждений. | На каждом из трёх поддержанных parser adapters превышено 1000 transport events, охвачено 20 funded clients и отдельный poor account. У ReadURL — 0 end-to-end events; статусные отказы не засчитаны как работающий адаптер. |
| MC-46 | BLOCKED | >=30 минут смешанной нагрузки/рестартов/отмен, задокументированные метрики, соблюдены заранее установленные пределы. | Реальная смешанная нагрузка шла 1800.314s плюс 19.059s drain, с двумя перезапусками и 117 отменами и соблюдёнными поддержанными пределами. Нарушений нет;5 malformed-report unknown holds сохранены для ручной сверки. Полный охват адаптеров не выполнен из-за закрытого ReadURL. |
| MC-47 | BLOCKED | Живая проверка трёх маркетплейсов и обычных сайтов по выборке; сверка цены, актуальности, условий, квот; естественная CAPTCHA честно отражена. | Живые provider requests0. Требуемые 9marketplace cards+10ordinary URLs/5domains и независимая сверка цены/условий/quota не выполнены; fixture-цены не подменяют живую выборку. |
| MC-48 | BLOCKED | Сравнение настроечного и рабочего промптов, реальные токены/usage/расходы и сверка квитанций; проверка экономии без снижения точности. | Проверены два коротких prompt-helper режима, но нет реальных setup/working ReadURL usage/receipts. Длины текста и max_tokens не объявлены фактической денежной экономией. |
| MC-49 | PASS | Chromium/Opera, темы, размеры, все сценарии/роли и актуальная полная регрессия единой сборки; без скрытых пропусков. | Полная 103-module regression подтверждена квалификацией целых модулей на том жеSHA; исходные ошибки среды сохранены. Chromium и actual Opera исполнили по 83parents+50subtests;587 loader entries покрыты через проверенную карту,504aliases не выданы за выполненные PASS. |
| MC-50 | PASS | Один воспроизводимый кандидат, актуальная база, миграции, backup/restore/rollback, единый комплект доказательств, документация, финансовая сверка; до выкладки отдельный допуск. | Подтверждены storage14, restore21, 6fa rollback27/final reopen16 и текущий c592 code11/final reopen16 на той же синтетической копии. Production fingerprints одинаковы. Проверены 31 обязательный evidence-файл и 7 deliverables, воспроизводимость bundle локально и его точные байты на сервере. Исходный ZIP независимо проверен на Alisa: 2169 записей, 2168 контрольных сумм файлов и 228 ссылок на доказательства из матрицы. Редакция отчётности r2 не меняет код, первичные журналы и результаты тестов. Окончательные байты выдаваемого контейнера подтверждаются отдельным внешним DELIVERY_MANIFEST; GitHub-публикация и передача владельцу не выводятся из статуса MC-50. Выкладка не выполнялась. |
| DUAL-01 | PASS | Реестр всех пользовательских операций в области релиза сопоставлен с элементом UI и доступным инструментом/командой чата. Нет операций, которые доступны только в одном канале. | Все 15 пользовательских registry operations имеют кабинетный элемент и chat command/tool; подтверждены пользовательские поля/фильтры, общий handler и оба независимых lifecycle. Служебная CSV-пагинация явно отделена от пользовательской выгрузки периода. |
| DUAL-02 | PASS | На одинаковых исходных данных и параметрах оба входа вызывают один авторитетный обработчик и дают эквивалентный результат, состояние БД и квитанцию. | Exact HTTP/chat и оба браузера подтверждают общие ID/версии/БД/квитанции при одинаковых пользовательских запросах. Raw transport page presentation не заявлена как отдельная одинаковая пользовательская настройка. |
| DUAL-03 | PASS | Полный сценарий через кабинет при отключённом DeepSeek и отсутствии монет; ноль вызовов модели. | Локальные кабинетные операции выполняются с отключённым DeepSeek и нулём монет; модель не вызывается. Недопущенная платная проверка останавливается до внешней отправки, что сохраняет общий финансовый контракт. |
| DUAL-04 | PASS | Полный сценарий через чат без открытия разделов кабинета; все обязательные поля, разрешения и подтверждения соблюдены. | Исполнен полный независимый chat-only цикл, включая уточнение, controls, история/CSV и подтверждённое удаление. Для выполнения этих операций переход в кабинет не нужен; точные команды и native cards используют тот же handler. |
| DUAL-05 | PASS | Взаимная видимость изменений, одинаковые ошибки, отмена, восстановление и защита от дублей, включая смену канала во время работы с задачей. | Cross-surface lifecycle, оригинальный вопрос в штатной истории, stale/version/replay/cancel/recovery проверены. После штатного обновления обе поверхности читают одно состояние; смена канала не создаёт новую оплату или задачу. |
| DUAL-06 | PASS | Проверены одинаковая изоляция клиентов, роли, запреты и безопасный ввод секретов. | Общая server-side изоляция scope/ролей и запрет подставных actor, workspace и secret подтверждены. Current-role projection и общий stale-response fence одинаково защищают расходы в таблице и chat card. |
| DUAL-07 | PASS | Ревью исходников подтверждает отсутствие дублирующих расчётов и параллельной архитектуры; оба пути используют общий контракт и ядро. | Ревью исходников подтверждает один typed execute, общий timer/ledger/delivery и серверные Decimal/finance расчёты. UI выполняет ввод и представление, включая точные координаты графика, без второй бизнес-модели. |
| DUAL-08 | PASS | Каждая новая функция сразу проектируется и реализуется для обоих способов управления. Неполный паритет отмечается как дефект/блокер, а не как принятая функция. | Операции сразу имеют обе surface bindings; выявленные локальные расхождения представлены отдельными исправлениями и проверены на финальномSHA. Неработающий paid ReadURL и прочие обязательные ветви остаются BLOCKED, а не принятой функцией. |

Все точные case IDs, исходные/квалифицированные результаты, отдельные движки, portable paths и SHA-256 сохранены в matrix-proposal.json. Критерий PASS не заменяет обязательный BLOCKED соседнего критерия; source/helper/controlled transport не выдаются за live.

CSV-паритет: Кабинет выгружает весь выбранный набор, агрегируя CSV-страницы с limit=5000 и серверным курсором. Exact chat export дополнительно сохраняет запрошенную страницу limit/before. Ручной ввод raw export.limit/before в кабинете не заявлен; паритет оценивается по одинаковым пользовательским фильтрам, результирующему набору и авторитетному обработчику.

## Сценарии, ожидаемые результаты и записи команд

Ниже перечислены реальные case IDs и обязательные ветви каждого критерия. Команды не реконструированы: ссылки ведут к сохранённым invocation/command/manifest; точные argv и окружение остаются в raw evidence. У source review нет выдуманной runtime-команды. Неисполненные ветви не объявлены пройденными.

### MC-01 — PASS

Область сценария: typed local contract.

Ожидаемые обязательные результаты:

- Все15 operations с действующим handler
- Input/output JSON schemas и typed errors/progress
- Server scope, роли, эффекты, подтверждение

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_registry_has_real_handlers_and_both_surface_bindings` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_scope_fields_and_provider_results_are_not_arguments` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

### MC-02 — PASS

Область сценария: UI/chat parity.

Ожидаемые обязательные результаты:

- Один execute, IDs/state/replay для обеих поверхностей
- Все пользовательские параметры15 операций доступны обеим поверхностям; служебную пагинацию выполняет адаптер
- Все8DUAL отдельно, без автоматического наследования PASS

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_exact_chat_and_http_share_ids_state_replay_and_no_model` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_exact_read_commands_keep_only_validated_view_queries` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_06_schedule_precision_roundtrip_and_status_filters_on_both_surfaces` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A008 — `evidence/duality-scope-review.json`.

### MC-03 — PASS

Область сценария: independent user lifecycles.

Ожидаемые обязательные результаты:

- Полный UI-only lifecycle
- Полный chat-only lifecycle
- Exact chat command без разговорного LLM
- Локальные действия с нулём монет; платное чтение отвергнуто до отправки

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_no_money_contract_grant_and_blocked_read_url_no_paid_attempt` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_local_history_and_settings_do_not_need_any_coins` (unittest).

Сохранённые записи команд/параметров исполнения: A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-04 — PASS

Область сценария: shared architecture.

Ожидаемые обязательные результаты:

- Общий timer/jobs/schedule/store
- Общие parser orders, limiter, billing и delivery
- Нет собственного cron/кошелька/очереди

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

### MC-05 — PASS

Область сценария: ownership and access.

Ожидаемые обязательные результаты:

- Guest и чужой пользователь
- Несколько мастерских/аккаунтов
- Текущая роль и scope перед чтением/изменением/отправкой

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_guest_and_forged_scope_are_denied` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_owner_workshop_isolation_on_every_read` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_cross_account_financial_link_is_refused` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_twenty_tenants_have_independent_identity_and_no_foreign_operations` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_03_guest_two_accounts_no_cost_fields_and_no_cross_scope_mutation` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-06 — PASS

Область сценария: item admission and naming.

Ожидаемые обязательные результаты:

- Только URL на базовом первом экране
- Автоназвание после подтверждённого результата, optional manual name240
- Безопасный URL и canonical exact-position dedup

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_url_only_add_canonical_deduplication_and_no_paid_or_scheduled_effect` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_named_override_is_preserved_after_automatic_title` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_secure_urls_and_precise_platform_routing` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_06_schedule_precision_roundtrip_and_status_filters_on_both_surfaces` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-07 — PASS

Область сценария: deterministic source routing.

Ожидаемые обязательные результаты:

- Ozon/WB/YM exact host/card identity
- Остальные публичные домены в web
- Ноль LLM для маршрутизации; похожие домены не присваивают чужой источник

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_secure_urls_and_precise_platform_routing` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_exact_market_routes_and_canonical_identity` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_durable_payload_and_row_correlations_reject_injection` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

### MC-08 — BLOCKED

Область сценария: Ozon provider contract.

Ожидаемые обязательные результаты:

- Точная карточка Ozon и цена нужного поля
- Фактические provider units/receipt
- Без поисковых/отзывных/LLM запросов

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_all_market_card_requests_and_documented_pending_balance_semantics` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_exact_fractional_prices_and_small_data_projection` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`.

**Не исполнено:** Живая проверка карточек Ozon и независимая сверка цены/условий/квитанции. Нет живой квитанции и независимой сверки требуемой выборки; synthetic supplier не засчитывается как live.

### MC-09 — BLOCKED

Область сценария: WB provider contract.

Ожидаемые обязательные результаты:

- Точная карточка WB
- Размер/вариант, регион, тип цены
- Фактическая цена и unit receipt

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_all_market_card_requests_and_documented_pending_balance_semantics` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_supported_region_and_yandex_moscow_constraint` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_old_price_unavailability_identity_sku_and_size_are_not_success` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`.

**Не исполнено:** Живая проверка карточек Wildberries и независимая сверка цены/варианта/квитанции. Нет живой квитанции и независимой сверки требуемой выборки; synthetic supplier не засчитывается как live.

### MC-10 — BLOCKED

Область сценария: YM provider contract.

Ожидаемые обязательные результаты:

- Точная карточка YM и SKU
- Подтверждённый московский региональный контракт
- Фактическая цена и unit receipt

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_all_market_card_requests_and_documented_pending_balance_semantics` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_supported_region_and_yandex_moscow_constraint` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_old_price_unavailability_identity_sku_and_size_are_not_success` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`.

**Не исполнено:** Живая проверка карточек Яндекс Маркета и независимая сверка цены/SKU/квитанции. Нет живой квитанции и независимой сверки требуемой выборки; synthetic supplier не засчитывается как live.

### MC-11 — PASS

Область сценария: shared parser financial lifecycle.

Ожидаемые обязательные результаты:

- Shared quote/reserve до сети
- Оригинальный order ID, poll/download/receipt
- Exact settlement и отсутствие double charge

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_enqueue_is_atomic_no_network_cookie_independent_and_hidden_in_legacy_route` (unittest).
- `tests.test_purchase_price_providers.PriceOrderBoundary.test_unknown_acceptance_and_revocation_reconcile_original_without_rebuy` (unittest).
- `tests.test_purchase_price_providers.PriceOrderBoundary.test_missing_or_conflicting_receipt_keeps_hold_and_never_charges_an_estimate` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).
- `tests.test_parser_market_service.ParserMarketService.test_dynamic_admin_price_pinned_receipts_and_real_ledger` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`.

### MC-12 — PASS

Область сценария: marketplace local clarification.

Ожидаемые обязательные результаты:

- Одна реальная структурированная неоднозначность
- Выбор стабильного basis ID без фиксации числовой цены
- Ноль LLM при точном выборе

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceContract.test_choice_pins_basis_without_pinning_price` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_answer_updates_one_template_closes_question_and_replays_once` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-13 — BLOCKED

Область сценария: Read URL integration.

Ожидаемые обязательные результаты:

- Production dispatch через общий gateway
- Служебные blocks и final usage в общем учёте
- Полная регрессия действующих chat routes

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `production gateway binds monitoring grant and closes contract before key, wallet or upstream` (node).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_read_url_production_guard_blocks_before_transport_and_billing` (unittest).

Сохранённые записи команд/параметров исполнения: A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A015 — `evidence/regression/manifest.json`, A016 — `evidence/qualified/run-manifest.json`, A017 — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/manifest.json`, A018 — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/manifest.json`, A019 — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/manifest.json`, A020 — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/manifest.json`, A021 — `evidence/qualified/modules/tests.test_shared_document_contract/raw/manifest.json`, A022 — `evidence/qualified/modules/tests.test_shared_web_flow/raw/manifest.json`, A023 — `evidence/qualified/modules/tests.test_transfer_finance/raw/manifest.json`, A024 — `evidence/regression/modules/000-tests.test_account_access/invocation.json`, A025 — `evidence/regression/modules/001-tests.test_admin_balance_alerts/invocation.json`, A026 — `evidence/regression/modules/002-tests.test_admin_costs/invocation.json`, A027 — `evidence/regression/modules/003-tests.test_admin_provider_balances/invocation.json`, A028 — `evidence/regression/modules/004-tests.test_admin_statistics/invocation.json`, A029 — `evidence/regression/modules/005-tests.test_browser_session/invocation.json`, A030 — `evidence/regression/modules/006-tests.test_capability_contracts/invocation.json`, A031 — `evidence/regression/modules/007-tests.test_catalog/invocation.json`, A032 — `evidence/regression/modules/008-tests.test_chat_api/invocation.json`, A033 — `evidence/regression/modules/009-tests.test_checkout/invocation.json`, A034 — `evidence/regression/modules/010-tests.test_coin_wallet/invocation.json`, A035 — `evidence/regression/modules/011-tests.test_deepseek_only_v32/invocation.json`, A036 — `evidence/regression/modules/012-tests.test_direct_gateway_authority_v32/invocation.json`, A037 — `evidence/regression/modules/013-tests.test_dispatch/invocation.json`, A038 — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/modules/000-tests.test_files_independent_regressions/invocation.json`, A039 — `evidence/regression/modules/015-tests.test_guest_activity/invocation.json`, A040 — `evidence/regression/modules/016-tests.test_guest_quota_shared/invocation.json`, A041 — `evidence/regression/modules/017-tests.test_guest_registration/invocation.json`, A042 — `evidence/regression/modules/018-tests.test_guest_selector/invocation.json`, A043 — `evidence/regression/modules/019-tests.test_identity/invocation.json`, A044 — `evidence/regression/modules/020-tests.test_market_dual_contract/invocation.json`, A045 — `evidence/regression/modules/021-tests.test_market_dual_native/invocation.json`, A046 — `evidence/regression/modules/022-tests.test_market_quantity_domain_boundaries/invocation.json`, A047 — `evidence/regression/modules/023-tests.test_market_quantity_history/invocation.json`, A048 — `evidence/regression/modules/024-tests.test_market_quantity_history_completion/invocation.json`, A049 — `evidence/regression/modules/025-tests.test_market_quantity_identity_quota/invocation.json`, A050 — `evidence/regression/modules/026-tests.test_market_quantity_intervals/invocation.json`, A051 — `evidence/regression/modules/027-tests.test_market_quantity_maturity_windows/invocation.json`, A052 — `evidence/regression/modules/028-tests.test_market_quantity_providers/invocation.json`, A053 — `evidence/regression/modules/029-tests.test_market_quantity_runtime/invocation.json`, A054 — `evidence/regression/modules/030-tests.test_marketplace_transfer_merge/invocation.json`, A055 — `evidence/regression/modules/031-tests.test_mastersckaya_domain_v29/invocation.json`, A056 — `evidence/regression/modules/032-tests.test_mcp/invocation.json`, A057 — `evidence/regression/modules/033-tests.test_media_capacity/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A058 — `evidence/regression/modules/035-tests.test_podmasterye_accounting/invocation.json`, A059 — `evidence/regression/modules/036-tests.test_podmasterye_admin_v12/invocation.json`, A060 — `evidence/regression/modules/037-tests.test_podmasterye_agent_first/invocation.json`, A061 — `evidence/regression/modules/038-tests.test_podmasterye_foundation/invocation.json`, A062 — `evidence/regression/modules/039-tests.test_podmasterye_guest_calculator_v25/invocation.json`, A063 — `evidence/regression/modules/040-tests.test_podmasterye_guest_v17/invocation.json`, A064 — `evidence/regression/modules/041-tests.test_podmasterye_market_analytics/invocation.json`, A065 — `evidence/regression/modules/042-tests.test_podmasterye_market_links/invocation.json`, A066 — `evidence/regression/modules/043-tests.test_podmasterye_market_planning/invocation.json`, A067 — `evidence/regression/modules/044-tests.test_podmasterye_matrix_v11/invocation.json`, A068 — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/modules/000-tests.test_podmasterye_media_v13/invocation.json`, A069 — `evidence/regression/modules/046-tests.test_podmasterye_owner_v18/invocation.json`, A070 — `evidence/regression/modules/047-tests.test_podmasterye_owner_v19/invocation.json`, A071 — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/modules/000-tests.test_podmasterye_owner_v21/invocation.json`, A072 — `evidence/regression/modules/049-tests.test_podmasterye_profit_v26/invocation.json`, A073 — `evidence/regression/modules/050-tests.test_podmasterye_provider_v16/invocation.json`, A074 — `evidence/regression/modules/051-tests.test_podmasterye_public_v22/invocation.json`, A075 — `evidence/regression/modules/052-tests.test_podmasterye_public_v23/invocation.json`, A076 — `evidence/regression/modules/053-tests.test_podmasterye_quality/invocation.json`, A077 — `evidence/regression/modules/054-tests.test_podmasterye_seasonal/invocation.json`, A078 — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/modules/000-tests.test_podmasterye_seasonal_mcp/invocation.json`, A079 — `evidence/regression/modules/056-tests.test_podmasterye_single_workshop_v20/invocation.json`, A080 — `evidence/regression/modules/057-tests.test_podmasterye_yandex_market/invocation.json`, A081 — `evidence/regression/modules/058-tests.test_podmasterye_yandex_sales/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A082 — `evidence/regression/modules/060-tests.test_purchase_monitoring_delivery/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A083 — `evidence/regression/modules/063-tests.test_purchase_monitoring_retry_faults/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A085 — `evidence/qualified/modules/tests.test_shared_document_contract/raw/modules/000-tests.test_shared_document_contract/invocation.json`, A086 — `evidence/regression/modules/067-tests.test_shared_web_access/invocation.json`, A087 — `evidence/qualified/modules/tests.test_shared_web_flow/raw/modules/000-tests.test_shared_web_flow/invocation.json`, A088 — `evidence/regression/modules/069-tests.test_storage/invocation.json`, A089 — `evidence/regression/modules/070-tests.test_timer/invocation.json`, A090 — `evidence/regression/modules/071-tests.test_transfer_ai_history/invocation.json`, A091 — `evidence/regression/modules/072-tests.test_transfer_ai_live_acceptance/invocation.json`, A092 — `evidence/regression/modules/073-tests.test_transfer_analytics/invocation.json`, A093 — `evidence/qualified/modules/tests.test_transfer_finance/raw/modules/000-tests.test_transfer_finance/invocation.json`, A094 — `evidence/regression/modules/075-tests.test_transfer_finance_payments/invocation.json`, A095 — `evidence/regression/modules/076-tests.test_transfer_lifecycle/invocation.json`, A096 — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json`, A097 — `evidence/regression/modules/078-tests.test_web_admission/invocation.json`, A098 — `evidence/regression/modules/079-tests.test_workshop_permissions_v30/invocation.json`, A099 — `evidence/regression/modules/080-tests.test_workshop_provider_boundary/invocation.json`, A100 — `evidence/regression/modules/081-tests.test_workshop_timer/invocation.json`, A101 — `evidence/regression/modules/082-tests.test_workshop_timer_http/invocation.json`, A102 — `evidence/regression/modules/083-tests.test_workshop_timer_native/invocation.json`, A103 — `evidence/regression/modules/084-usage-reconciliation.test_operation_grants/invocation.json`, A104 — `evidence/regression/modules/085-usage-reconciliation.test_operation_summary/invocation.json`, A105 — `evidence/regression/modules/086-usage-reconciliation.test_reconcile/invocation.json`, A106 — `evidence/regression/modules/087-native.assistant-preferences.test.mjs/invocation.json`, A107 — `evidence/regression/modules/088-native.capability-filter.test.mjs/invocation.json`, A108 — `evidence/regression/modules/089-native.chat-worker.test.mjs/invocation.json`, A109 — `evidence/regression/modules/090-native.guest-selector.test.mjs/invocation.json`, A110 — `evidence/regression/modules/091-native.native-compaction.test.mjs/invocation.json`, A111 — `evidence/regression/modules/092-native.native-spill.test.mjs/invocation.json`, A112 — `evidence/regression/modules/093-native.platform-mcp.test.mjs/invocation.json`, A113 — `evidence/regression/modules/094-native.private-input.test.mjs/invocation.json`, A114 — `evidence/regression/modules/095-native.public-events.test.mjs/invocation.json`, A115 — `evidence/regression/modules/096-native.timer-setup.test.mjs/invocation.json`, A116 — `evidence/regression/modules/097-native.transfer-ai-contract.test.mjs/invocation.json`, A117 — `evidence/regression/modules/098-native.web-evidence.test.mjs/invocation.json`, A118 — `evidence/regression/modules/100-gateway.server.test.mjs/invocation.json`, A119 — `evidence/regression/modules/101-usage-reconciliation.test_gateway.mjs/invocation.json`, A120 — `evidence/regression/modules/102-usage-reconciliation.test_operation_gateway.mjs/invocation.json`.

Проверка/сопоставление существующих доказательств, без нового запуска: A121 — `evidence/regression-qualified/result.json`, A122 — `evidence/qualified/result.json`.

**Не исполнено:** Действующая оплачиваемая ReadURL-композиция dispatch/tool-result/usage/settlement. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-14 — BLOCKED

Область сценария: ordinary-site setup.

Ожидаемые обязательные результаты:

- Полученная публичная цена обычного сайта
- Автоназвание без лишнего вопроса
- Сохранённый индивидуальный короткий locator

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_setup_persists_only_compact_metadata_and_exact_price` (unittest).
- `verified read receipt and final usage preserve small decimal prices and compact data` (node).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Первоначальная настройка обычного сайта через действующий оплачиваемый ReadURL. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-15 — BLOCKED

Область сценария: ordinary-site working prompt.

Ожидаемые обязательные результаты:

- URL+name+short approved rule
- Flash/thinking disabled/no history/no Search
- Обычный рабочий успех ровно одно чтение

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `one short native Messages request per card, two modes, no caller tools/history/budget` (node).

Сохранённые записи команд/параметров исполнения: A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Реальное короткое настроечное и рабочее оплачиваемое чтение обычной страницы. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-16 — BLOCKED

Область сценария: integrated read rejection.

Ожидаемые обязательные результаты:

- HTTP200 без подтверждённого tool call отвергнут
- web_fetch_tool_result_error отвергнут
- Production integration не публикует цену

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `HTTP 200, text price, partial usage or unmatched tool are insufficient evidence` (node).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_unverified_tool_or_wrong_url_never_publishes_a_price` (unittest).

Сохранённые записи команд/параметров исполнения: A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`.

**Не исполнено:** Проверка результата чтения и final usage внутри действующего оплачиваемого ReadURL-пути. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. validateResponse сейчас чистый fixture parser; он не потребляется активной paid route.

### MC-17 — BLOCKED

Область сценария: identity and exact price meaning.

Ожидаемые обязательные результаты:

- URL/product/region/currency/unit/basis
- Exact decimal без float или округления
- Отказ старой/рекламной/корзинной цены
- Read URL receipt integration

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_invalid_and_float_prices_rollback_without_zero` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_semantic_change_requires_confirmation_and_new_series` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_exact_fractional_prices_and_small_data_projection` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_packaging_filter_values_remain_in_price_meaning` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_identity_mismatch_keeps_last_price_and_records_actual_supplier_charge` (unittest).
- `exact decimal price uses the shared 18 integral and 18 fractional digit boundary` (node).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Цена/URL/регион/смысл цены из подтверждённого действующего ReadURL-исполнения. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-18 — PASS

Область сценария: shared question publication.

Ожидаемые обязательные результаты:

- Один item/version/run-bound question
- Реальные варианты из supplier response
- Pending state в таблице и native chat publication

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_clarification_is_one_shared_question_and_blocks_checks` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-19 — PASS

Область сценария: atomic shared answer.

Ожидаемые обязательные результаты:

- UI/chat закрывают один вопрос и меняют одну версию
- Stale/duplicate/concurrent answer без новой независимой задачи
- Обе поверхности показывают новое состояние

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_answer_updates_one_template_closes_question_and_replays_once` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_free_answer_is_compact_and_cannot_change_scope_or_url` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_free_clarification_preserves_full_declared_instruction_bound` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_stale_control_has_no_effect` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-20 — BLOCKED

Область сценария: clarification follow-up.

Ожидаемые обязательные результаты:

- После ответа новый check по short rule
- До ответа платных циклов нет
- Выбор переживает нехватку средств

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_clarification_choice_survives_financial_pause` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_clarification_is_one_shared_question_and_blocks_checks` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`.

**Не исполнено:** Проверка обычного сайта по уточнённому короткому ReadURL-правилу. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-21 — BLOCKED

Область сценария: controlled reconfiguration.

Ожидаемые обязательные результаты:

- Перестройка обычной страницы запускает контролируемую перенастройку
- Изменение смысла цены требует вопроса/новой серии
- Нет ложного изменения по несопоставимой базе

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_locator_move_preserves_comparison_and_increments_template` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_semantic_change_requires_confirmation_and_new_series` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_changed_url_preserves_old_history_without_showing_old_price_as_new` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`.

**Не исполнено:** Фактическая перестройка изменившейся обычной страницы через ReadURL. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-22 — BLOCKED

Область сценария: CAPTCHA policy.

Ожидаемые обязательные результаты:

- CAPTCHA подтверждена на transport boundary
- Наблюдение пропущено, старая цена и следующее окно сохранены
- Нет обхода/быстрого платного цикла

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_active_captcha_preserves_last_price_and_next_schedule` (unittest).
- `explicit CAPTCHA and login pages remain distinct from unverified tool failures` (node).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** CAPTCHA на действующем ReadURL-пути с сохранением подтверждённой цены. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Пока выполнен domain outcome test, не runtime web fault.

### MC-23 — BLOCKED

Область сценария: authentication wall policy.

Ожидаемые обязательные результаты:

- Провайдер действительно сообщает auth wall
- Остановка конкретного товара
- Никакого хранения/использования учётных данных сайта

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_auth_required_pauses_only_product_without_cookies` (unittest).
- `explicit CAPTCHA and login pages remain distinct from unverified tool failures` (node).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Требование входа на действующем ReadURL-пути без обхода авторизации. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Пока выполнен domain outcome test, не runtime web fault.

### MC-24 — BLOCKED

Область сценария: honest unavailable outcomes.

Ожидаемые обязательные результаты:

- No product/no price/404/410/blocked/unknown различимы
- Ошибки не создают observation0
- Все применимые transport branches

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_unavailable_and_schema_errors_never_create_zero_observations` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_waiting_retry_has_checkpoint_without_confirmed_zero` (unittest).
- `tests.test_purchase_price_providers.PriceContract.test_old_price_unavailability_identity_sku_and_size_are_not_success` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_identity_mismatch_keeps_last_price_and_records_actual_supplier_charge` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_progress_projects_only_current_unfinished_timer_run` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`.

**Не исполнено:** Полный набор исходов обычного сайта в действующем ReadURL runtime. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-25 — BLOCKED

Область сценария: rate-limit fault matrix.

Ожидаемые обязательные результаты:

- 429 на каждой send/poll/download/receipt стадии и Read URL stages
- Три подряд, persistent, absent/corrupt/numeric/date Retry-After
- Shared cooldown/checkpoint и свободный worker

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_shared_supplier_cooldown_blocks_other_jobs_without_holding_worker` (unittest).
- `tests.test_purchase_price_providers.PriceOrderBoundary.test_preflight_transient_retries_are_bounded_and_never_dispatch` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_429_shared_cooldown_prevents_early_retry_and_duplicate_reserve` (unittest).
- `tests.test_parser_market_service.ParserMarketService.test_rate_limit_bounded_retry_and_explicit_rejection` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_429_balance_date_numeric_absent_malformed_then_success` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_429_send_date_numeric_absent_malformed_then_success` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_429_poll_date_numeric_absent_malformed_then_success` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_429_download_date_numeric_absent_malformed_then_success` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_persistent_preflight_429_exhausts_budget_without_send` (unittest).
- `tests.test_purchase_monitoring_retry_faults.MonitoringRetryFaults.test_persistent_send_429_exhausts_budget_without_second_reserve` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_progress_projects_only_current_unfinished_timer_run` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A083 — `evidence/regression/modules/063-tests.test_purchase_monitoring_retry_faults/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`.

**Не исполнено:** 429/Retry-After/backoff/checkpoint на сетевых стадиях действующего ReadURL. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-26 — BLOCKED

Область сценария: typed network/schema faults.

Ожидаемые обязательные результаты:

- 400/401/403/422/5xx/timeout/TLS/schema по всем применимым стадиям
- Типизированное действие с ограниченным retry
- Нет обхода доступа

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceContract.test_transport_failure_categories_do_not_blindly_retry_tls` (unittest).
- `tests.test_purchase_price_providers.PriceOrderBoundary.test_missing_or_conflicting_receipt_keeps_hold_and_never_charges_an_estimate` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_unavailable_and_schema_errors_never_create_zero_observations` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_preflight_permanent_matrix_never_sends_or_repeats` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_confirmed_send_http_rejection_is_zero_and_typed_pause` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_permanent_poll_and_download_statuses_keep_original_paid_order` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_ambiguous_tls_or_schema_send_survives_restart_then_real_admin_reconciles` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_after_accept_5xx_timeout_and_reset_only_poll_original_order` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_temporary_poll_and_download_errors_release_worker_then_recover_same_order` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_preflight_temporary_503_recovers_without_second_reserve` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_active_schedule_permanent_error_cannot_create_next_occurrence_purchase` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_receipt_missing_invalid_identity_and_overrun_never_estimate_charge` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`.

**Не исполнено:** Permanent/transient/TLS/timeout/schema fault matrix действующего ReadURL. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-27 — BLOCKED

Область сценария: unknown paid outcome.

Ожидаемые обязательные результаты:

- Unknown держит original IDs/reserve
- Повторная покупка до сверки невозможна
- Reconcile исходной квитанции после restart/cancel
- Неизвестный расход не0

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_price_providers.PriceOrderBoundary.test_unknown_acceptance_and_revocation_reconcile_original_without_rebuy` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_unknown_submission_recovers_original_receipt_after_application_restart` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_cancel_after_unknown_send_preserves_finance_without_publishing_price` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_original_ledger_settlement_unblocks_unknown_without_fabricating_price` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_reconciled_unknown_preserves_later_manual_stop` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_ambiguous_tls_or_schema_send_survives_restart_then_real_admin_reconciles` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_common_capped_overrun_settlement_unblocks_unknown_without_rebilling` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_actual_admin_overrun_resolution_and_scheduler_maintenance_clear_unknown` (unittest).

Сохранённые записи команд/параметров исполнения: A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`.

**Не исполнено:** Неизвестные оплаченные ReadURL usage/settlement и сверка исходной попытки без повторной покупки. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Parser unknown acceptance и исходная квитанция проверяются отдельно; неизвестный paid ReadURL usage/settlement не исполнен.

### MC-28 — PASS

Область сценария: shared timer controls.

Ожидаемые обязательные результаты:

- Все schedule kinds/fields/zone/microseconds
- Все критерии и каналы
- Manual/start/pause/resume/stop/delete на общем timer

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_monitoring_schedule_all_shapes_exact_microseconds_and_json_bound` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_explicit_schedule_start_pause_resume_stop_without_history_loss` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_completed_once_keeps_delivery_fence_and_requires_new_future_start` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_06_schedule_precision_roundtrip_and_status_filters_on_both_surfaces` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_progress_projects_only_current_unfinished_timer_run` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-29 — PASS

Область сценария: durable scheduled authority.

Ожидаемые обязательные результаты:

- Без открытой вкладки и stale cookie
- Finite item/template/run authorization до dispatch
- Current role/lifecycle/cancel/version
- Restart/missed windows без backfill

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_provider_authority_requires_finite_live_lease_and_active_owner` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_queued_grant_is_exact_original_attempt_finite_and_revocable` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_provider_payload_must_match_authorized_url_region_and_selection` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_cancel_or_settings_change_revokes_worker_authority_and_publication` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_scheduled_occurrence_uses_same_domain_binding_and_coalesces_missed_windows` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_unknown_submission_recovers_original_receipt_after_application_restart` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

### MC-30 — PASS

Область сценария: occurrence and lease uniqueness.

Ожидаемые обязательные результаты:

- Request/occurrence uniqueness
- Manual/scheduled overlap
- Concurrent claims + expired finite lease без новой покупки

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_overlapping_commands_reuse_one_shared_timer_occurrence` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_concurrent_same_request_has_one_item_and_one_event` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_100_parallel_and_1000_same_id_use_one_paid_attempt_and_observation` (unittest).
- `tests.test_purchase_price_providers.PriceOrderBoundary.test_finite_lease_expiry_defers_original_reserve_until_same_run_renews` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`.

### MC-31 — PASS

Область сценария: exact notification arithmetic.

Ожидаемые обязательные результаты:

- all/change/increase/decrease/amount/percent/threshold crossing
- Exact decimal boundary и zero base
- First observation, repeated threshold and incompatible series без ложных сигналов

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.NotificationArithmetic.test_all_rule_shapes_and_exact_money` (unittest).
- `tests.test_purchase_monitoring.NotificationArithmetic.test_first_base_threshold_repeats_and_zero_percent` (unittest).
- `tests.test_purchase_monitoring.NotificationArithmetic.test_multiple_matching_rules_are_returned_once_for_one_delivery` (unittest).
- `tests.test_purchase_monitoring.NotificationArithmetic.test_invalid_thresholds_and_unknown_rules_fail_closed` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_semantic_change_requires_confirmation_and_new_series` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`.

### MC-32 — BLOCKED

Область сценария: real monitoring notification composition.

Ожидаемые обязательные результаты:

- Actual scheduled monitoring result → общий timer → native chat
- TelegramIntegration с настоящим scoped consent, внешний sender controlled
- Chat/Telegram/both, same result, dedup
- Unknown не повторяется; disconnect/reconnect без новой цены
- Ноль chat.turn LLM
- Отдельная живая проверка Telegram по §14D

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_delivery.PurchaseMonitoringDelivery.test_same_monitoring_result_delivers_both_or_telegram_only_once` (unittest).
- `tests.test_purchase_monitoring_delivery.PurchaseMonitoringDelivery.test_unknown_monitoring_telegram_delivery_cannot_be_resent_or_rebought` (unittest).
- `tests.test_purchase_monitoring_delivery.PurchaseMonitoringDelivery.test_disconnect_and_reconnect_deliver_original_monitoring_without_new_price` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).
- `tests.test_workshop_timer.Execution.test_telegram_rate_limit_respects_retry_time_and_bound` (unittest).

Сохранённые записи команд/параметров исполнения: A082 — `evidence/regression/modules/060-tests.test_purchase_monitoring_delivery/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A100 — `evidence/regression/modules/081-tests.test_workshop_timer/invocation.json`.

**Не исполнено:** Живая Telegram-доставка разрешённому тестовому аккаунту по §14D. §14D прямо требует реальные Telegram/баланс с разрешённым тестовым аккаунтом. Actual native и controlled Telegram sender подтверждают интеграцию, но не живую доставку.

### MC-33 — BLOCKED

Область сценария: shared exact financial accounting.

Ожидаемые обязательные результаты:

- Parser units + DeepSeek input/cache/output
- Pinned versions тарифов/курса
- Нет двойного server-tool/standaloneFetch учёта

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_transfer_service_billing.LedgerBoundaries.test_existing_deepseek_web_and_file_costs_are_not_duplicated_or_counted_as_tokens` (unittest).
- `tests.test_transfer_service_billing.LedgerBoundaries.test_partial_settlement_and_duplicate_receipt` (unittest).
- `tests.test_parser_market_service.ParserMarketService.test_dynamic_admin_price_pinned_receipts_and_real_ledger` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).

Сохранённые записи команд/параметров исполнения: A096 — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`.

**Не исполнено:** Предметные ReadURL input/cache/output usage и окончательный общий settlement. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-34 — BLOCKED

Область сценария: proven reserve upper bound.

Ожидаемые обязательные результаты:

- Резерв до каждой paid stage
- Доказанная cumulative upper bound
- Exact/insufficient/sufficient balances и concurrent reserve

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_parser_market_service.ParserMarketService.test_balance_shortfall_exact_and_zero` (unittest).
- `tests.test_parser_market_service.ParserMarketService.test_duplicate_and_cross_customer_quota` (unittest).
- `tests.test_transfer_service_billing.LedgerBoundaries.test_reservation_enforces_quota_balance_and_credential` (unittest).
- `production gateway binds monitoring grant and closes contract before key, wallet or upstream` (node).

Сохранённые записи команд/параметров исполнения: A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A096 — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Подтверждённая совокупная оплачиваемая ReadURL-граница и резерв до отправки. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-35 — BLOCKED

Область сценария: financial pause and recovery.

Ожидаемые обязательные результаты:

- Неотправленный вызов не списан
- Один эпизод уведомления, choice/history/progress сохранены
- Top-up resumes толькоfinancial pause; нет backfill
- Mid-stage continuation only with new reserve

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_financial_notice_is_once_per_account_and_only_financial_pause_resumes` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_clarification_choice_survives_financial_pause` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_wallet_recovery_only_resumes_financial_pause` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_manual_controls_close_funds_episode_without_reviving_stopped_tasks` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`.

**Не исполнено:** Баланс разрешённого живого тестового аккаунта по §14D. §14D требует проверку баланса разрешённого живого тестового аккаунта. Controlled wallet/top-up и финансовые эпизоды доказаны отдельно; живой проверки нет.

### MC-36 — BLOCKED

Область сценария: provider constraints and admin alert.

Ожидаемые обязательные результаты:

- Provider quota/balance/credentials отличаются от клиентских монет
- Штатный admin episode/delivery fence
- Paused task и отсутствие лишних расходов

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_provider_pause_uses_existing_admin_notice_once_without_private_item` (unittest).
- `tests.test_parser_market_service.ParserMarketService.test_revoked_session_pause_and_supplier_shortfall` (unittest).
- `tests.test_transfer_service_billing.LedgerBoundaries.test_reservation_enforces_quota_balance_and_credential` (unittest).
- `tests.test_purchase_monitoring_transport_faults.MonitoringTransportFaults.test_tls_pause_uses_existing_admin_notice_episode` (unittest).

Сохранённые записи команд/параметров исполнения: A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A096 — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`, A123 — `evidence/supplementary-quota/manifest.json`.

**Не исполнено:** ReadURL provider balance/quota constraint и штатное admin-уведомление. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Parser supplier balance/quota и штатное admin-уведомление оцениваются отдельно по supplementary-quota; ReadURL provider-balance ветвь не исполнена.

### MC-37 — BLOCKED

Область сценария: admin table costs.

Ожидаемые обязательные результаты:

- Admin-only setup/clarification/check/errors/diagnostic breakdown
- Tokens/model/type/units и same authoritative ledger
- Unknown costs отображены не0

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_costs_use_authoritative_attempts_and_role_is_rechecked` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_unknown_cost_is_not_zero_and_attempt_cannot_be_reused` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_02_admin_costs_are_current_role_only_and_purge_on_downgrade` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

**Не исполнено:** Реальные ReadURL token-cost записи настройки/проверок в административной таблице. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Parser admin API→DOM projection, роли и отсутствие утечек доказываются отдельно. Настроечные/рабочие ReadURL token usage и их окончательная себестоимость ещё не получены через предметный runtime.

### MC-38 — BLOCKED

Область сценария: admin inline chat costs.

Ожидаемые обязательные результаты:

- Техническая строка под соответствующим native result
- Same run/attempt table/admin ledger
- Нет повторного расхода/постоянных приватных сумм в истории

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_02_admin_costs_are_current_role_only_and_purge_on_downgrade` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

**Не исполнено:** Реальные ReadURL token-cost записи настройки/проверок в административной chat card. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Parser admin API→DOM projection, роли и отсутствие утечек доказываются отдельно. Настроечные/рабочие ReadURL token usage и их окончательная себестоимость ещё не получены через предметный runtime.

### MC-39 — PASS

Область сценария: no private cost leakage.

Ожидаемые обязательные результаты:

- Member/guest UI, DOM, API, stream/history/export/model projection
- Downgrade current role и stale response purge
- Штатный собственный wallet сохранён

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_costs_use_authoritative_attempts_and_role_is_rechecked` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_real_parser_shared_scheduler_receipt_and_private_projection` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_02_admin_costs_are_current_role_only_and_purge_on_downgrade` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_03_guest_two_accounts_no_cost_fields_and_no_cross_scope_mutation` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-40 — PASS

Область сценария: compact indexed retention.

Ожидаемые обязательные результаты:

- Нет HTML/photos/reviews/reasoning в compact metadata
- Индексы/серверная пагинация
- Измерение1000×365 с индексами/WAL и заявленными ограничениями

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_setup_persists_only_compact_metadata_and_exact_price` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_history_pagination_exact_aggregates_and_bounded_chart` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A009 — `evidence/spec-review-invocations.json`.

### MC-41 — PASS

Область сценария: local exact history and chart.

Ожидаемые обязательные результаты:

- Exact aggregates/series/filtered history+export
- Gaps не нули и серии не соединены
- 0 model/external calls для расчёта
- Локальный просмотр при недоступном поставщике

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_history_pagination_exact_aggregates_and_bounded_chart` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_local_history_and_settings_do_not_need_any_coins` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_07_chart_preserves_distinct_prices_beyond_binary_float_precision` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-42 — PASS

Область сценария: retention and confirmed deletion.

Ожидаемые обязательные результаты:

- Pause/stop сохраняют историю
- Delete требуетconfirm+currentversion, останавливает task
- Предметные данные очищены, finance/receipt retained

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_delete_purges_subject_data_but_retains_ledger_and_idempotent_tombstone` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_explicit_schedule_start_pause_resume_stop_without_history_loss` (unittest).
- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_cancel_after_unknown_send_preserves_finance_without_publishing_price` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### MC-43 — BLOCKED

Область сценария: URL and tool security.

Ожидаемые обязательные результаты:

- SSRF/URL/private hosts/secondaryURL/secrets
- Redirect confinement доказана
- Website injection не расширяет tools/scope
- No provider mutations/secret leak

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_secure_urls_and_precise_platform_routing` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_scope_fields_and_provider_results_are_not_arguments` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_provider_payload_must_match_authorized_url_region_and_selection` (unittest).
- `URL and text admission do not permit private/secondary/marketplace URLs or secrets` (node).
- `production gateway binds monitoring grant and closes contract before key, wallet or upstream` (node).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

**Не исполнено:** Принудительное ограничение redirect/tool scope действующего внешнего ReadURL. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-44 — PASS

Область сценария: concurrency and replay stress.

Ожидаемые обязательные результаты:

- 100 одновременно и1000 same-request commands
- Одна logical task/paid attempt/observation
- Ноль duplicate side effects

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_100_parallel_and_1000_same_id_use_one_paid_attempt_and_observation` (unittest).

Сохранённые записи команд/параметров исполнения: A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A124 — `evidence/stress/run-manifest.json`, A125 — `evidence/stress/command-events.jsonl`.

### MC-45 — BLOCKED

Область сценария: per-adapter stress volume.

Ожидаемые обязательные результаты:

- >=1000 transport events КАЖДОГО adapter, включаяReadURL
- >=20 clients
- Shared quota/fairness/isolation
- Serial+random faults без corruption

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_resilience.MonitoringResilience.test_twenty_tenants_have_independent_identity_and_no_foreign_operations` (unittest).

Сохранённые записи команд/параметров исполнения: A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A124 — `evidence/stress/run-manifest.json`, A125 — `evidence/stress/command-events.jsonl`.

**Не исполнено:** Не менее 1000 end-to-end событий работающего ReadURL-адаптера. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-46 — BLOCKED

Область сценария: 30-minute mixed stress.

Ожидаемые обязательные результаты:

- >=1800 real seconds непрерывной смешанной нагрузки
- Restarts/cancels/faults
- До прогона зафиксированы thresholds, все metrics и исходные журналы
- Все применимые adapters

Сохранённые записи команд/параметров исполнения: A124 — `evidence/stress/run-manifest.json`, A125 — `evidence/stress/command-events.jsonl`.

**Не исполнено:** Работающий ReadURL в полном обязательном охвате смешанной нагрузки. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута.

### MC-47 — BLOCKED

Область сценария: live external acceptance.

Ожидаемые обязательные результаты:

- >=3 live card каждогоOzon/WB/YM
- >=10 ordinary URLs на>=5domains
- Независимая публичная сверка цены/условий/актуальности/quota
- ЕстественнаяCAPTCHA честно зафиксирована

**Не исполнено:** Живые 3×3 marketplace-карточки и 10 обычных URL на 5 доменах с независимой сверкой. Нет живой квитанции и независимой сверки требуемой выборки; synthetic supplier не засчитывается как live.

### MC-48 — BLOCKED

Область сценария: actual prompt economy.

Ожидаемые обязательные результаты:

- Setup vs working prompt
- Реальные input/cache/output usage и supplier receipts
- Подтверждённая экономия без потери точности

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `one short native Messages request per card, two modes, no caller tools/history/budget` (node).

Сохранённые записи команд/параметров исполнения: A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`.

**Не исполнено:** Фактические оплаченные setup/working ReadURL usage/receipts для проверки экономии. Production Read URL закрыт: cumulative_token_bound_unverified и redirect_scope_unverified. Helper/contract fixtures не являются исполнением этого маршрута. Длины prompts/max_tokens и старые эксперименты не являются фактическими расходами этого кандидата.

### MC-49 — PASS

Область сценария: complete integrated regression.

Ожидаемые обязательные результаты:

- Chromium и actual Opera, обе темы, mobile/desktop, все роли
- Все объявленные cases плюс14 distinct-fixture executions на каждом движке; точное число из current audit
- Все expanded loader entries retained with covered_by proof, aliases не выдаются за выполненные PASS
- Весь актуальный backend/native набор одного SHA; no hidden skip

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_02_admin_costs_are_current_role_only_and_purge_on_downgrade` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_03_guest_two_accounts_no_cost_fields_and_no_cross_scope_mutation` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_06_schedule_precision_roundtrip_and_status_filters_on_both_surfaces` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_07_chart_preserves_distinct_prices_beyond_binary_float_precision` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A015 — `evidence/regression/manifest.json`, A016 — `evidence/qualified/run-manifest.json`, A017 — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/manifest.json`, A018 — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/manifest.json`, A019 — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/manifest.json`, A020 — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/manifest.json`, A021 — `evidence/qualified/modules/tests.test_shared_document_contract/raw/manifest.json`, A022 — `evidence/qualified/modules/tests.test_shared_web_flow/raw/manifest.json`, A023 — `evidence/qualified/modules/tests.test_transfer_finance/raw/manifest.json`, A024 — `evidence/regression/modules/000-tests.test_account_access/invocation.json`, A025 — `evidence/regression/modules/001-tests.test_admin_balance_alerts/invocation.json`, A026 — `evidence/regression/modules/002-tests.test_admin_costs/invocation.json`, A027 — `evidence/regression/modules/003-tests.test_admin_provider_balances/invocation.json`, A028 — `evidence/regression/modules/004-tests.test_admin_statistics/invocation.json`, A029 — `evidence/regression/modules/005-tests.test_browser_session/invocation.json`, A030 — `evidence/regression/modules/006-tests.test_capability_contracts/invocation.json`, A031 — `evidence/regression/modules/007-tests.test_catalog/invocation.json`, A032 — `evidence/regression/modules/008-tests.test_chat_api/invocation.json`, A033 — `evidence/regression/modules/009-tests.test_checkout/invocation.json`, A034 — `evidence/regression/modules/010-tests.test_coin_wallet/invocation.json`, A035 — `evidence/regression/modules/011-tests.test_deepseek_only_v32/invocation.json`, A036 — `evidence/regression/modules/012-tests.test_direct_gateway_authority_v32/invocation.json`, A037 — `evidence/regression/modules/013-tests.test_dispatch/invocation.json`, A038 — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/modules/000-tests.test_files_independent_regressions/invocation.json`, A039 — `evidence/regression/modules/015-tests.test_guest_activity/invocation.json`, A040 — `evidence/regression/modules/016-tests.test_guest_quota_shared/invocation.json`, A041 — `evidence/regression/modules/017-tests.test_guest_registration/invocation.json`, A042 — `evidence/regression/modules/018-tests.test_guest_selector/invocation.json`, A043 — `evidence/regression/modules/019-tests.test_identity/invocation.json`, A044 — `evidence/regression/modules/020-tests.test_market_dual_contract/invocation.json`, A045 — `evidence/regression/modules/021-tests.test_market_dual_native/invocation.json`, A046 — `evidence/regression/modules/022-tests.test_market_quantity_domain_boundaries/invocation.json`, A047 — `evidence/regression/modules/023-tests.test_market_quantity_history/invocation.json`, A048 — `evidence/regression/modules/024-tests.test_market_quantity_history_completion/invocation.json`, A049 — `evidence/regression/modules/025-tests.test_market_quantity_identity_quota/invocation.json`, A050 — `evidence/regression/modules/026-tests.test_market_quantity_intervals/invocation.json`, A051 — `evidence/regression/modules/027-tests.test_market_quantity_maturity_windows/invocation.json`, A052 — `evidence/regression/modules/028-tests.test_market_quantity_providers/invocation.json`, A053 — `evidence/regression/modules/029-tests.test_market_quantity_runtime/invocation.json`, A054 — `evidence/regression/modules/030-tests.test_marketplace_transfer_merge/invocation.json`, A055 — `evidence/regression/modules/031-tests.test_mastersckaya_domain_v29/invocation.json`, A056 — `evidence/regression/modules/032-tests.test_mcp/invocation.json`, A057 — `evidence/regression/modules/033-tests.test_media_capacity/invocation.json`, A013 — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json`, A058 — `evidence/regression/modules/035-tests.test_podmasterye_accounting/invocation.json`, A059 — `evidence/regression/modules/036-tests.test_podmasterye_admin_v12/invocation.json`, A060 — `evidence/regression/modules/037-tests.test_podmasterye_agent_first/invocation.json`, A061 — `evidence/regression/modules/038-tests.test_podmasterye_foundation/invocation.json`, A062 — `evidence/regression/modules/039-tests.test_podmasterye_guest_calculator_v25/invocation.json`, A063 — `evidence/regression/modules/040-tests.test_podmasterye_guest_v17/invocation.json`, A064 — `evidence/regression/modules/041-tests.test_podmasterye_market_analytics/invocation.json`, A065 — `evidence/regression/modules/042-tests.test_podmasterye_market_links/invocation.json`, A066 — `evidence/regression/modules/043-tests.test_podmasterye_market_planning/invocation.json`, A067 — `evidence/regression/modules/044-tests.test_podmasterye_matrix_v11/invocation.json`, A068 — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/modules/000-tests.test_podmasterye_media_v13/invocation.json`, A069 — `evidence/regression/modules/046-tests.test_podmasterye_owner_v18/invocation.json`, A070 — `evidence/regression/modules/047-tests.test_podmasterye_owner_v19/invocation.json`, A071 — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/modules/000-tests.test_podmasterye_owner_v21/invocation.json`, A072 — `evidence/regression/modules/049-tests.test_podmasterye_profit_v26/invocation.json`, A073 — `evidence/regression/modules/050-tests.test_podmasterye_provider_v16/invocation.json`, A074 — `evidence/regression/modules/051-tests.test_podmasterye_public_v22/invocation.json`, A075 — `evidence/regression/modules/052-tests.test_podmasterye_public_v23/invocation.json`, A076 — `evidence/regression/modules/053-tests.test_podmasterye_quality/invocation.json`, A077 — `evidence/regression/modules/054-tests.test_podmasterye_seasonal/invocation.json`, A078 — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/modules/000-tests.test_podmasterye_seasonal_mcp/invocation.json`, A079 — `evidence/regression/modules/056-tests.test_podmasterye_single_workshop_v20/invocation.json`, A080 — `evidence/regression/modules/057-tests.test_podmasterye_yandex_market/invocation.json`, A081 — `evidence/regression/modules/058-tests.test_podmasterye_yandex_sales/invocation.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A082 — `evidence/regression/modules/060-tests.test_purchase_monitoring_delivery/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A011 — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json`, A083 — `evidence/regression/modules/063-tests.test_purchase_monitoring_retry_faults/invocation.json`, A084 — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json`, A012 — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json`, A085 — `evidence/qualified/modules/tests.test_shared_document_contract/raw/modules/000-tests.test_shared_document_contract/invocation.json`, A086 — `evidence/regression/modules/067-tests.test_shared_web_access/invocation.json`, A087 — `evidence/qualified/modules/tests.test_shared_web_flow/raw/modules/000-tests.test_shared_web_flow/invocation.json`, A088 — `evidence/regression/modules/069-tests.test_storage/invocation.json`, A089 — `evidence/regression/modules/070-tests.test_timer/invocation.json`, A090 — `evidence/regression/modules/071-tests.test_transfer_ai_history/invocation.json`, A091 — `evidence/regression/modules/072-tests.test_transfer_ai_live_acceptance/invocation.json`, A092 — `evidence/regression/modules/073-tests.test_transfer_analytics/invocation.json`, A093 — `evidence/qualified/modules/tests.test_transfer_finance/raw/modules/000-tests.test_transfer_finance/invocation.json`, A094 — `evidence/regression/modules/075-tests.test_transfer_finance_payments/invocation.json`, A095 — `evidence/regression/modules/076-tests.test_transfer_lifecycle/invocation.json`, A096 — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json`, A097 — `evidence/regression/modules/078-tests.test_web_admission/invocation.json`, A098 — `evidence/regression/modules/079-tests.test_workshop_permissions_v30/invocation.json`, A099 — `evidence/regression/modules/080-tests.test_workshop_provider_boundary/invocation.json`, A100 — `evidence/regression/modules/081-tests.test_workshop_timer/invocation.json`, A101 — `evidence/regression/modules/082-tests.test_workshop_timer_http/invocation.json`, A102 — `evidence/regression/modules/083-tests.test_workshop_timer_native/invocation.json`, A103 — `evidence/regression/modules/084-usage-reconciliation.test_operation_grants/invocation.json`, A104 — `evidence/regression/modules/085-usage-reconciliation.test_operation_summary/invocation.json`, A105 — `evidence/regression/modules/086-usage-reconciliation.test_reconcile/invocation.json`, A106 — `evidence/regression/modules/087-native.assistant-preferences.test.mjs/invocation.json`, A107 — `evidence/regression/modules/088-native.capability-filter.test.mjs/invocation.json`, A108 — `evidence/regression/modules/089-native.chat-worker.test.mjs/invocation.json`, A109 — `evidence/regression/modules/090-native.guest-selector.test.mjs/invocation.json`, A110 — `evidence/regression/modules/091-native.native-compaction.test.mjs/invocation.json`, A111 — `evidence/regression/modules/092-native.native-spill.test.mjs/invocation.json`, A112 — `evidence/regression/modules/093-native.platform-mcp.test.mjs/invocation.json`, A113 — `evidence/regression/modules/094-native.private-input.test.mjs/invocation.json`, A114 — `evidence/regression/modules/095-native.public-events.test.mjs/invocation.json`, A115 — `evidence/regression/modules/096-native.timer-setup.test.mjs/invocation.json`, A116 — `evidence/regression/modules/097-native.transfer-ai-contract.test.mjs/invocation.json`, A117 — `evidence/regression/modules/098-native.web-evidence.test.mjs/invocation.json`, A014 — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json`, A118 — `evidence/regression/modules/100-gateway.server.test.mjs/invocation.json`, A119 — `evidence/regression/modules/101-usage-reconciliation.test_gateway.mjs/invocation.json`, A120 — `evidence/regression/modules/102-usage-reconciliation.test_operation_gateway.mjs/invocation.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A126 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_accounting_browser/command.json`, A127 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_agent_ui/command.json`, A128 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json`, A129 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json`, A130 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_ui/command.json`, A131 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_independent_ui/command.json`, A132 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_layout/command.json`, A133 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_market_ui/command.json`, A134 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json`, A135 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json`, A136 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json`, A137 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v22_ui/command.json`, A138 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v23_ui/command.json`, A139 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v24_ui/command.json`, A140 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_seasonal_ui/command.json`, A141 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json`, A142 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json`, A143 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json`, A144 — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json`, A145 — `evidence/browser/chromium/modules/tests.browser.test_service_price_form/command.json`, A146 — `evidence/browser/chromium/modules/tests.browser.test_transfer_ai_ui/command.json`, A147 — `evidence/browser/chromium/modules/tests.browser.test_transfer_finance_ui/command.json`, A148 — `evidence/browser/chromium/modules/tests.browser.test_transfer_shell_ui/command.json`, A149 — `evidence/browser/chromium/modules/tests.browser.test_workshop_permissions_v30_ui/command.json`, A150 — `evidence/browser/chromium/modules/tests.browser.test_workshop_timer_ui/command.json`, A151 — `evidence/browser/chromium/modules/tests.test_market_dual_browser/command.json`, A007 — `evidence/browser/opera/run-manifest.json`, A152 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_accounting_browser/command.json`, A153 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_agent_ui/command.json`, A154 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json`, A155 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json`, A156 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_ui/command.json`, A157 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_independent_ui/command.json`, A158 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_layout/command.json`, A159 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_market_ui/command.json`, A160 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json`, A161 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json`, A162 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json`, A163 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v22_ui/command.json`, A164 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v23_ui/command.json`, A165 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v24_ui/command.json`, A166 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_seasonal_ui/command.json`, A167 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json`, A168 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json`, A169 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json`, A170 — `evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json`, A171 — `evidence/browser/opera/modules/tests.browser.test_service_price_form/command.json`, A172 — `evidence/browser/opera/modules/tests.browser.test_transfer_ai_ui/command.json`, A173 — `evidence/browser/opera/modules/tests.browser.test_transfer_finance_ui/command.json`, A174 — `evidence/browser/opera/modules/tests.browser.test_transfer_shell_ui/command.json`, A175 — `evidence/browser/opera/modules/tests.browser.test_workshop_permissions_v30_ui/command.json`, A176 — `evidence/browser/opera/modules/tests.browser.test_workshop_timer_ui/command.json`, A177 — `evidence/browser/opera/modules/tests.test_market_dual_browser/command.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

Проверка/сопоставление существующих доказательств, без нового запуска: A122 — `evidence/qualified/result.json`, A121 — `evidence/regression-qualified/result.json`.

### MC-50 — PASS

Область сценария: reproducible delivery and safe rollback.

Ожидаемые обязательные результаты:

- Один currentbase+candidatеSHA, manifests/hashes/docs/migrations
- Backup/restore в новый каталог
- Actual previous6fa code oncopy затемfinal reopen
- Current productionc592 code onsyntheticcopy затемFINAL reopen
- Finance retained/quiesce unresolved gate
- Единый комплект evidence; no deployment без отдельного owner admission

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_versioned_migration_repeat_and_foreign_keys` (unittest).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A009 — `evidence/spec-review-invocations.json`, A178 — `evidence/rollback-6fa/old-invocation.json`, A179 — `evidence/rollback-production/invocation.json`.

Проверка/сопоставление существующих доказательств, без нового запуска: A180 — `evidence/delivery-assembly.json`, A181 — `evidence/mc50-delivery-review.json`.

**Условие публикации:** Publish MC50 PASS only after verified final ZIP/container and all member hashes. The external DELIVERY_MANIFEST binds the final archive; no archive self-hash appears inside it.

### DUAL-01 — PASS

Область сценария: operation/form contract parity.

Ожидаемые обязательные результаты:

- Все15 registry operations mapped to UI controls and exact chat commands
- Всеfields including once/multitime/units/status/historyfilters/export/costspager

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_registry_has_real_handlers_and_both_surface_bindings` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_06_schedule_precision_roundtrip_and_status_filters_on_both_surfaces` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A008 — `evidence/duality-scope-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### DUAL-02 — PASS

Область сценария: equivalent authority.

Ожидаемые обязательные результаты:

- Один authoritativeexecute
- Эквивалентные IDs/DBstate/receipt на равных inputs

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_exact_chat_and_http_share_ids_state_replay_and_no_model` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A008 — `evidence/duality-scope-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### DUAL-03 — PASS

Область сценария: local UI without conversational model or funds.

Ожидаемые обязательные результаты:

- Local operations с DeepSeekdisabled иcoins0
- No conversationalmodel call
- Paid provider check явно отвергается доdispatch при отсутствии допуска

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_local_history_and_settings_do_not_need_any_coins` (unittest).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_no_money_contract_grant_and_blocked_read_url_no_paid_attempt` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_03_guest_two_accounts_no_cost_fields_and_no_cross_scope_mutation` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_04_complete_lifecycle_only_in_cabinet` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`, A002 — `evidence/source-review.json`, A008 — `evidence/duality-scope-review.json`.

### DUAL-04 — PASS

Область сценария: chat-only complete lifecycle.

Ожидаемые обязательные результаты:

- Полный chat-only без cabinet navigation
- Обязательныеполя, права, подтверждения
- Exact command с теми жеtypedarguments

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_05_complete_lifecycle_only_in_chat` (browser; chromium, opera).
- `tests.test_purchase_monitoring_http.PurchaseMonitoringHttp.test_exact_chat_and_http_share_ids_state_replay_and_no_model` (unittest).

Сохранённые записи команд/параметров исполнения: A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A003 — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### DUAL-05 — PASS

Область сценария: cross-surface visibility and recovery.

Ожидаемые обязательные результаты:

- Pending question и изменения видны обоим каналам
- Одинаковыеerrors/staleversion/cancel/recovery
- Смена поверхности не дублируетоперацию

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_01_cabinet_and_chat_share_complete_price_lifecycle` (browser; chromium, opera).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_stale_control_has_no_effect` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_idempotency_replays_and_conflicting_parameters` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_answer_updates_one_template_closes_question_and_replays_once` (unittest).

Сохранённые записи команд/параметров исполнения: A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### DUAL-06 — PASS

Область сценария: same scope and role security.

Ожидаемые обязательные результаты:

- Same owner/workshop/current role
- Запретsecret/tool/scope injection
- Безопасныйserver-only secret input

Исполненные целевые случаи (результаты и final source guard указаны в JSON):

- `tests.test_purchase_monitoring.PurchaseMonitoring.test_guest_and_forged_scope_are_denied` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_owner_workshop_isolation_on_every_read` (unittest).
- `tests.test_purchase_monitoring.PurchaseMonitoring.test_public_scope_fields_and_provider_results_are_not_arguments` (unittest).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_02_admin_costs_are_current_role_only_and_purge_on_downgrade` (browser; chromium, opera).
- `tests.test_purchase_monitoring_browser.PurchaseMonitoringBrowser.test_03_guest_two_accounts_no_cost_fields_and_no_cross_scope_mutation` (browser; chromium, opera).

Сохранённые записи команд/параметров исполнения: A001 — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json`, A004 — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json`, A005 — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json`, A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

### DUAL-07 — PASS

Область сценария: one domain architecture.

Ожидаемые обязательные результаты:

- UI/chat одинаковый execute+registry
- Нет параллельного state/wallet/math/timer
- Display-only rounding не меняетserverDecimal

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`.

### DUAL-08 — PASS

Область сценария: release parity gate.

Ожидаемые обязательные результаты:

- Каждаяноваяoperation сразу имеетдвеsurfacebindings
- Неполныепараметры/сценарии фиксируютсядефектами
- Предыдущиеfailed/paritydiagnostics не скрыты

Сохранённые записи команд/параметров исполнения: A009 — `evidence/spec-review-invocations.json`, A006 — `evidence/browser/chromium/run-manifest.json`, A007 — `evidence/browser/opera/run-manifest.json`.

Manual/static review (не runtime PASS): A002 — `evidence/source-review.json`, A008 — `evidence/duality-scope-review.json`, A010 — `evidence/browser-audit/browser-inheritance-audit-c33a108.json`.

## Индекс записей команд и review-артефактов

SHA-256 вычислен по сохранённым байтам каждого файла. Записи выполнения, статические ревью и производные сверки различаются в JSON; ссылка сама по себе не повышает статус критерия.

| ID | Переносимый путь | SHA-256 |
|---|---|---|
| A001 | evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json — `evidence/regression/modules/059-tests.test_purchase_monitoring/invocation.json` | `9fc22e03d9c59be0624e197bf378766722c0096de829a0b291c872faf658ddad` |
| A002 | evidence/source-review.json — `evidence/source-review.json` | `aa0ac2710211c443723953c2559524b705bb7eebd49b3e69a51c9b0d70437a91` |
| A003 | evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json — `evidence/regression/modules/061-tests.test_purchase_monitoring_http/invocation.json` | `afc5c76ce1f6f4bffdfb21044b2c10d4339f235990c85fbb6044fdc0fe646c75` |
| A004 | evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json — `evidence/browser/chromium/modules/tests.test_purchase_monitoring_browser/command.json` | `09d054261c4976bbeec9d48e5b615329056031e66e99f5a3ff5651e6df739350` |
| A005 | evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json — `evidence/browser/opera/modules/tests.test_purchase_monitoring_browser/command.json` | `b8b38d0998d52f1f405fa8a137b4bcec115d70b4e88ff3720be361689261937e` |
| A006 | evidence/browser/chromium/run-manifest.json — `evidence/browser/chromium/run-manifest.json` | `da26b02b987a856b8caa5b108d8bcd8152da3ef0d4c432821537f8c3dc3b13ae` |
| A007 | evidence/browser/opera/run-manifest.json — `evidence/browser/opera/run-manifest.json` | `e7520037f435e5368f634e88d940df3a2ba87f466c78b2b5d0797074d2cf2631` |
| A008 | evidence/duality-scope-review.json — `evidence/duality-scope-review.json` | `a1d54b709f0bce7f9c6361355c5b6b9d3eb708231359c06bc75d00b242dd6099` |
| A009 | evidence/spec-review-invocations.json — `evidence/spec-review-invocations.json` | `b6b348285dc83bfda729502794db2185c7cc911e9cd1976bf2925e580f10fb25` |
| A010 | evidence/browser-audit/browser-inheritance-audit-c33a108.json — `evidence/browser-audit/browser-inheritance-audit-c33a108.json` | `d0b66797a323b060e7ebd426651a3084039967cf9358c9fcfe46950704b51b0c` |
| A011 | evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json — `evidence/regression/modules/062-tests.test_purchase_monitoring_resilience/invocation.json` | `9722ddab9c2ce9bcfde01dc45dfe496d72ca7c47c6caf13c8d38093b1a85da1f` |
| A012 | evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json — `evidence/regression/modules/065-tests.test_purchase_price_providers/invocation.json` | `cda98d390f9f2fe2942b3b9c02a25890f6415de2572e523d80a18189c4a0472e` |
| A013 | evidence/regression/modules/034-tests.test_parser_market_service/invocation.json — `evidence/regression/modules/034-tests.test_parser_market_service/invocation.json` | `72311ff5e884711a2656e3afdd522a5e28788c193d9a8a905e1a1de8f2cb2694` |
| A014 | evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json — `evidence/regression/modules/099-gateway.purchase-price-read-url.test.mjs/invocation.json` | `006f19f85e0e22c979d04b877361e7673a96a4af5a312cb92e433122ef1b6f3b` |
| A015 | evidence/regression/manifest.json — `evidence/regression/manifest.json` | `86dee03f84c38a9f27aa51778e2880da238283ab067359437df62bd1dcfb3df8` |
| A016 | evidence/qualified/run-manifest.json — `evidence/qualified/run-manifest.json` | `d89c34b59b4bf8f398d265f55d4703c7af1381cb9617d5199409ef9b7a56ef40` |
| A017 | evidence/qualified/modules/tests.test_files_independent_regressions/raw/manifest.json — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/manifest.json` | `09a643b0fbd95e05645b5724afed67ebccf6058d7dcf0e6ef9fcba725b571db3` |
| A018 | evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/manifest.json — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/manifest.json` | `264be3aa794a693d0d216cb9020999f24517bd2c67c13bc5cba0dcaccaa814cb` |
| A019 | evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/manifest.json — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/manifest.json` | `ae251872980a9a1b54172ca99e26e3ee870b8ea724a90d358ef11bdeeca0b856` |
| A020 | evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/manifest.json — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/manifest.json` | `8b2951343ac28dbe23a8c742f98ac6b0e768eec59d34ad646169066b6e7fdcce` |
| A021 | evidence/qualified/modules/tests.test_shared_document_contract/raw/manifest.json — `evidence/qualified/modules/tests.test_shared_document_contract/raw/manifest.json` | `3245f0990d698b0d6fcb377ce7c5e4b9cb54d676ec0764ef2142f51bcf6c699d` |
| A022 | evidence/qualified/modules/tests.test_shared_web_flow/raw/manifest.json — `evidence/qualified/modules/tests.test_shared_web_flow/raw/manifest.json` | `cce75372f4cd013eaec6b4037a7de27ef1e93147f88309ba3d575d030f57fc34` |
| A023 | evidence/qualified/modules/tests.test_transfer_finance/raw/manifest.json — `evidence/qualified/modules/tests.test_transfer_finance/raw/manifest.json` | `3917ecb25588a3c0eea1789ed1620575bd4567665259ce06e09955e2fb606874` |
| A024 | evidence/regression/modules/000-tests.test_account_access/invocation.json — `evidence/regression/modules/000-tests.test_account_access/invocation.json` | `50eed7fdefc3ace930eb7393d8b14ef91faa703dfe082fa743127c57cac35f4d` |
| A025 | evidence/regression/modules/001-tests.test_admin_balance_alerts/invocation.json — `evidence/regression/modules/001-tests.test_admin_balance_alerts/invocation.json` | `04df52cdcf1db3fc46b29a14c002182085779864540b1b48e75c26e418fedc1f` |
| A026 | evidence/regression/modules/002-tests.test_admin_costs/invocation.json — `evidence/regression/modules/002-tests.test_admin_costs/invocation.json` | `63ede7191a2c11ce675e2ac6fa29dbd67f95fdfb4483d2e774d82f3ae69284b5` |
| A027 | evidence/regression/modules/003-tests.test_admin_provider_balances/invocation.json — `evidence/regression/modules/003-tests.test_admin_provider_balances/invocation.json` | `786eb60cf4caaaf942ec4ad5b0ab87f70912ef183a94508e6466a6161ddcff98` |
| A028 | evidence/regression/modules/004-tests.test_admin_statistics/invocation.json — `evidence/regression/modules/004-tests.test_admin_statistics/invocation.json` | `c208a964481595c48c58faa009f64a26f540e4a666a6e742733d09ee1d53bd3f` |
| A029 | evidence/regression/modules/005-tests.test_browser_session/invocation.json — `evidence/regression/modules/005-tests.test_browser_session/invocation.json` | `6dbfd6216bde37adbddd54e052513a8f8640682fc4723f75dbf4b421157332cb` |
| A030 | evidence/regression/modules/006-tests.test_capability_contracts/invocation.json — `evidence/regression/modules/006-tests.test_capability_contracts/invocation.json` | `f036aae90c5b248191c3a61f95b42a79066e724d7aac69282c003140c0cd9230` |
| A031 | evidence/regression/modules/007-tests.test_catalog/invocation.json — `evidence/regression/modules/007-tests.test_catalog/invocation.json` | `3981424d70e142f0a22acfc0ad3343eeec41d67b55a3a222eea4fa6ca41e05cf` |
| A032 | evidence/regression/modules/008-tests.test_chat_api/invocation.json — `evidence/regression/modules/008-tests.test_chat_api/invocation.json` | `f149c6a4761337c9cb8424cd482b6299a5f36c25acab847a2323fbf7ff8af026` |
| A033 | evidence/regression/modules/009-tests.test_checkout/invocation.json — `evidence/regression/modules/009-tests.test_checkout/invocation.json` | `d01e8b3d8c06f36e49beea7f34d5836e34023f9964d027ac34443a9ec273e4f4` |
| A034 | evidence/regression/modules/010-tests.test_coin_wallet/invocation.json — `evidence/regression/modules/010-tests.test_coin_wallet/invocation.json` | `42f5867ce6ffcc4b8587c215c5f83850c9e618bec9ca74d351305a467a646762` |
| A035 | evidence/regression/modules/011-tests.test_deepseek_only_v32/invocation.json — `evidence/regression/modules/011-tests.test_deepseek_only_v32/invocation.json` | `549fadc2410128b8b9a57fdc0a2825121f1267c7ab4d051070e4163c615c77b8` |
| A036 | evidence/regression/modules/012-tests.test_direct_gateway_authority_v32/invocation.json — `evidence/regression/modules/012-tests.test_direct_gateway_authority_v32/invocation.json` | `50241785aca8e0c0c709c2995a9a96bbe8019baa931fbc52750f49cd465e3b92` |
| A037 | evidence/regression/modules/013-tests.test_dispatch/invocation.json — `evidence/regression/modules/013-tests.test_dispatch/invocation.json` | `015f5c9bc1379fa3b06c2a8805c83ba8e9a7ddf2add13d2196b890c83f2f0f51` |
| A038 | evidence/qualified/modules/tests.test_files_independent_regressions/raw/modules/000-tests.test_files_independent_regressions/invocation.json — `evidence/qualified/modules/tests.test_files_independent_regressions/raw/modules/000-tests.test_files_independent_regressions/invocation.json` | `a6665d3182bb940197934e62cb5e837529104d64af861d51993576719dcccbd9` |
| A039 | evidence/regression/modules/015-tests.test_guest_activity/invocation.json — `evidence/regression/modules/015-tests.test_guest_activity/invocation.json` | `29a16c381333015daa0385f0b1c263ff0fd828089e621b9f512a202f8ce814e5` |
| A040 | evidence/regression/modules/016-tests.test_guest_quota_shared/invocation.json — `evidence/regression/modules/016-tests.test_guest_quota_shared/invocation.json` | `cf0118239d1c710a4b65dbdf6f43044100d0a874c4a8a4c46a07192be33aaf10` |
| A041 | evidence/regression/modules/017-tests.test_guest_registration/invocation.json — `evidence/regression/modules/017-tests.test_guest_registration/invocation.json` | `b8d94b017c0d0f3387cdf135fde941c1a4ab884a1a998689c7e197e2e7152583` |
| A042 | evidence/regression/modules/018-tests.test_guest_selector/invocation.json — `evidence/regression/modules/018-tests.test_guest_selector/invocation.json` | `61908f8892d2fe8955f2dd9da4d4f8e1e7e72e730aa0f6ccec6401e7c3469d24` |
| A043 | evidence/regression/modules/019-tests.test_identity/invocation.json — `evidence/regression/modules/019-tests.test_identity/invocation.json` | `927ff2ea57df01fa736e400504feebf8fdedd73bb81cf8f6fd19a567b807abe8` |
| A044 | evidence/regression/modules/020-tests.test_market_dual_contract/invocation.json — `evidence/regression/modules/020-tests.test_market_dual_contract/invocation.json` | `255232284688a186c6fa21215db325d37d8afef9a7bdec241ab8f08a597c105f` |
| A045 | evidence/regression/modules/021-tests.test_market_dual_native/invocation.json — `evidence/regression/modules/021-tests.test_market_dual_native/invocation.json` | `3568cbc1365a52a2bfc5e4236803b8bb74b1649a5144e321d6e9e421a7f266fe` |
| A046 | evidence/regression/modules/022-tests.test_market_quantity_domain_boundaries/invocation.json — `evidence/regression/modules/022-tests.test_market_quantity_domain_boundaries/invocation.json` | `fd39815c702e62e063a9d7288ce8cc3527c46f738aa044de7a63d0403f535434` |
| A047 | evidence/regression/modules/023-tests.test_market_quantity_history/invocation.json — `evidence/regression/modules/023-tests.test_market_quantity_history/invocation.json` | `a041db962ee848ba1d1db7b62a446967886a5b672d589bcb79cf011efbe0236e` |
| A048 | evidence/regression/modules/024-tests.test_market_quantity_history_completion/invocation.json — `evidence/regression/modules/024-tests.test_market_quantity_history_completion/invocation.json` | `8aca086d3b53511c1c3b8814176db53be24ad56b15ee9ed11e9e8d94e58a4a71` |
| A049 | evidence/regression/modules/025-tests.test_market_quantity_identity_quota/invocation.json — `evidence/regression/modules/025-tests.test_market_quantity_identity_quota/invocation.json` | `01e2dbaf687c55ef25e3423c1791e5c35956ba36caba9660d19d69bef9fe8aad` |
| A050 | evidence/regression/modules/026-tests.test_market_quantity_intervals/invocation.json — `evidence/regression/modules/026-tests.test_market_quantity_intervals/invocation.json` | `ccc6055cd6744b110a7d961f5ee6ba383085799fec069411051b970ab2ab959c` |
| A051 | evidence/regression/modules/027-tests.test_market_quantity_maturity_windows/invocation.json — `evidence/regression/modules/027-tests.test_market_quantity_maturity_windows/invocation.json` | `6fb46c8ac5a832e6e88c41cd741efed0c503e0ee100773f4cffdafe2c1cdf168` |
| A052 | evidence/regression/modules/028-tests.test_market_quantity_providers/invocation.json — `evidence/regression/modules/028-tests.test_market_quantity_providers/invocation.json` | `56c896745eb34f95ffbb7eea6584da118ef2e6b74c23852d8b73251bbbdfe43a` |
| A053 | evidence/regression/modules/029-tests.test_market_quantity_runtime/invocation.json — `evidence/regression/modules/029-tests.test_market_quantity_runtime/invocation.json` | `07ffca38d57a9d1e31c1a95b3816bad80207dd90fa286ac32fb833515c3b607e` |
| A054 | evidence/regression/modules/030-tests.test_marketplace_transfer_merge/invocation.json — `evidence/regression/modules/030-tests.test_marketplace_transfer_merge/invocation.json` | `457e76166e3c67e5d60ccbbfaedfb50bd3eacad205d7ad4579c1d10d7f1b2308` |
| A055 | evidence/regression/modules/031-tests.test_mastersckaya_domain_v29/invocation.json — `evidence/regression/modules/031-tests.test_mastersckaya_domain_v29/invocation.json` | `edb4239c2e3ddb36065842bddf94e599f2753c2b8d574a5e93fe0672600a7379` |
| A056 | evidence/regression/modules/032-tests.test_mcp/invocation.json — `evidence/regression/modules/032-tests.test_mcp/invocation.json` | `4f69695d9a33e5604f7eeac8fbef9daaaef5000a40627a38df66b31c35562d2d` |
| A057 | evidence/regression/modules/033-tests.test_media_capacity/invocation.json — `evidence/regression/modules/033-tests.test_media_capacity/invocation.json` | `fd13e4cc6a5b5f79a52b27bdb42fb31ca305f82641c512cdbbcff713fe79a9d9` |
| A058 | evidence/regression/modules/035-tests.test_podmasterye_accounting/invocation.json — `evidence/regression/modules/035-tests.test_podmasterye_accounting/invocation.json` | `bedefa52f205dcc1def9803574ca800d717cef06a2e9b24d0fdd719c11b05812` |
| A059 | evidence/regression/modules/036-tests.test_podmasterye_admin_v12/invocation.json — `evidence/regression/modules/036-tests.test_podmasterye_admin_v12/invocation.json` | `23edf051742d08fd767d0931ee35de119eeb4433e0bf9ed8b4eb6ab6b4eb787e` |
| A060 | evidence/regression/modules/037-tests.test_podmasterye_agent_first/invocation.json — `evidence/regression/modules/037-tests.test_podmasterye_agent_first/invocation.json` | `41c092acc9e1e5f4f30f25e88f1ee2be5109e4930b30ad738ce068639d80e6ec` |
| A061 | evidence/regression/modules/038-tests.test_podmasterye_foundation/invocation.json — `evidence/regression/modules/038-tests.test_podmasterye_foundation/invocation.json` | `625c79f860e81ff9f9286461f0a9249c91dbba86b4760210bcc64e58492ca2c7` |
| A062 | evidence/regression/modules/039-tests.test_podmasterye_guest_calculator_v25/invocation.json — `evidence/regression/modules/039-tests.test_podmasterye_guest_calculator_v25/invocation.json` | `0aedacb0433841ea2ebdc3571903e23a68c4b1d3d662e7a6a513777d9c305a8e` |
| A063 | evidence/regression/modules/040-tests.test_podmasterye_guest_v17/invocation.json — `evidence/regression/modules/040-tests.test_podmasterye_guest_v17/invocation.json` | `102a120e0d79b67787bf9653669082201068b8113080a1f66ce706138a6d3278` |
| A064 | evidence/regression/modules/041-tests.test_podmasterye_market_analytics/invocation.json — `evidence/regression/modules/041-tests.test_podmasterye_market_analytics/invocation.json` | `c988543a7695476c00baa35e6a078b8c34e60cff6e506a9b355e9185136830da` |
| A065 | evidence/regression/modules/042-tests.test_podmasterye_market_links/invocation.json — `evidence/regression/modules/042-tests.test_podmasterye_market_links/invocation.json` | `61f2948da5884537435e7879b142d3ac355150b438df6b89c87113147344d0df` |
| A066 | evidence/regression/modules/043-tests.test_podmasterye_market_planning/invocation.json — `evidence/regression/modules/043-tests.test_podmasterye_market_planning/invocation.json` | `c169d013634f709305ceae2c8ba7d6f19c63b0827c310515618f2cde3e8e0a4c` |
| A067 | evidence/regression/modules/044-tests.test_podmasterye_matrix_v11/invocation.json — `evidence/regression/modules/044-tests.test_podmasterye_matrix_v11/invocation.json` | `03abdd5d0e0edeb9d788ac2f8c3610fbad85fa02110aca0575409eff535d066e` |
| A068 | evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/modules/000-tests.test_podmasterye_media_v13/invocation.json — `evidence/qualified/modules/tests.test_podmasterye_media_v13/raw/modules/000-tests.test_podmasterye_media_v13/invocation.json` | `18ede0a1c833efd3ca238160dd1c1f7d3e26de9295ae9c1796a27ad6745e6b31` |
| A069 | evidence/regression/modules/046-tests.test_podmasterye_owner_v18/invocation.json — `evidence/regression/modules/046-tests.test_podmasterye_owner_v18/invocation.json` | `c9212b2753ed20fd3f2e4cfbfa575b4588e5c9c9b863ff5320bfb4ebc293f8ba` |
| A070 | evidence/regression/modules/047-tests.test_podmasterye_owner_v19/invocation.json — `evidence/regression/modules/047-tests.test_podmasterye_owner_v19/invocation.json` | `35f0bb2ecb3f7e78b852172206ea16567b7425724f7b0a2b373ed65b92575410` |
| A071 | evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/modules/000-tests.test_podmasterye_owner_v21/invocation.json — `evidence/qualified/modules/tests.test_podmasterye_owner_v21/raw/modules/000-tests.test_podmasterye_owner_v21/invocation.json` | `1656f7ac75eb26f5d0fb4f0296ec7db8a30a36f8da8779226672cc7632cd902b` |
| A072 | evidence/regression/modules/049-tests.test_podmasterye_profit_v26/invocation.json — `evidence/regression/modules/049-tests.test_podmasterye_profit_v26/invocation.json` | `f645950923543378631ee319e904b966ed7e02a2a27f8a6c91c41fcc786b9145` |
| A073 | evidence/regression/modules/050-tests.test_podmasterye_provider_v16/invocation.json — `evidence/regression/modules/050-tests.test_podmasterye_provider_v16/invocation.json` | `cc411d637f88cedb09974fdf12249c56d788d9081fa87a6c53dc568c6380f77c` |
| A074 | evidence/regression/modules/051-tests.test_podmasterye_public_v22/invocation.json — `evidence/regression/modules/051-tests.test_podmasterye_public_v22/invocation.json` | `b312446c85efff83af2f445749887c012237194f50775f33f3341763f7b7f09f` |
| A075 | evidence/regression/modules/052-tests.test_podmasterye_public_v23/invocation.json — `evidence/regression/modules/052-tests.test_podmasterye_public_v23/invocation.json` | `b2596af0a2f8dd4bd1be859c389c6b41eb474412c5d54646e6d7fcc871e2b675` |
| A076 | evidence/regression/modules/053-tests.test_podmasterye_quality/invocation.json — `evidence/regression/modules/053-tests.test_podmasterye_quality/invocation.json` | `a540cc607ade399df8b94acacd959c61c79fbab206ccdfb5c8a4c5d6ac66673d` |
| A077 | evidence/regression/modules/054-tests.test_podmasterye_seasonal/invocation.json — `evidence/regression/modules/054-tests.test_podmasterye_seasonal/invocation.json` | `5b71fcd5be70bb76605848037eb99c7521f937485e817c703085a64dda4b44d8` |
| A078 | evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/modules/000-tests.test_podmasterye_seasonal_mcp/invocation.json — `evidence/qualified/modules/tests.test_podmasterye_seasonal_mcp/raw/modules/000-tests.test_podmasterye_seasonal_mcp/invocation.json` | `55e853ee007f4d301f5693b96cda687c7c3951c95de2fef1e7585ccd1c746cfe` |
| A079 | evidence/regression/modules/056-tests.test_podmasterye_single_workshop_v20/invocation.json — `evidence/regression/modules/056-tests.test_podmasterye_single_workshop_v20/invocation.json` | `8314a28af85694ce768fedcd7511d61ea52eb78d7f5c84449e0b14778deaef36` |
| A080 | evidence/regression/modules/057-tests.test_podmasterye_yandex_market/invocation.json — `evidence/regression/modules/057-tests.test_podmasterye_yandex_market/invocation.json` | `4f1db5e70e0943da795c0245c0e2432831c9f76f367c0315c0773614e7f6efe7` |
| A081 | evidence/regression/modules/058-tests.test_podmasterye_yandex_sales/invocation.json — `evidence/regression/modules/058-tests.test_podmasterye_yandex_sales/invocation.json` | `3c64f74a6509bad59154fd68bab1d8802bf3719b48d04f05a3a905b87a90d162` |
| A082 | evidence/regression/modules/060-tests.test_purchase_monitoring_delivery/invocation.json — `evidence/regression/modules/060-tests.test_purchase_monitoring_delivery/invocation.json` | `88a914e6b382d80aa4dddf1e94d6a531fc0fb7fe0955b06e62d23823aec88bdd` |
| A083 | evidence/regression/modules/063-tests.test_purchase_monitoring_retry_faults/invocation.json — `evidence/regression/modules/063-tests.test_purchase_monitoring_retry_faults/invocation.json` | `e4eff38a78086584cdf0253eeadf42ef038ed8070d27a94719333a8270ac44f7` |
| A084 | evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json — `evidence/regression/modules/064-tests.test_purchase_monitoring_transport_faults/invocation.json` | `29c509dd7043448027e9364a0582e3a01e987112b6996345766f1e081502283c` |
| A085 | evidence/qualified/modules/tests.test_shared_document_contract/raw/modules/000-tests.test_shared_document_contract/invocation.json — `evidence/qualified/modules/tests.test_shared_document_contract/raw/modules/000-tests.test_shared_document_contract/invocation.json` | `9df22282f282abb2843f983258b531b5466ce5f319c1f9ff133bc320077c8c07` |
| A086 | evidence/regression/modules/067-tests.test_shared_web_access/invocation.json — `evidence/regression/modules/067-tests.test_shared_web_access/invocation.json` | `f8f2e34e0ed1d180907a62a3be439475c6f18637b4aa756229c05c60733a7bbc` |
| A087 | evidence/qualified/modules/tests.test_shared_web_flow/raw/modules/000-tests.test_shared_web_flow/invocation.json — `evidence/qualified/modules/tests.test_shared_web_flow/raw/modules/000-tests.test_shared_web_flow/invocation.json` | `9d1a4405620b3049284f51ebbd4beb2798c0207ee40f98bcbfe56f28e3f1dc82` |
| A088 | evidence/regression/modules/069-tests.test_storage/invocation.json — `evidence/regression/modules/069-tests.test_storage/invocation.json` | `00f3b68da29070204326ec0151e78513438d412fae05a5422747174cb67cd2ee` |
| A089 | evidence/regression/modules/070-tests.test_timer/invocation.json — `evidence/regression/modules/070-tests.test_timer/invocation.json` | `f0bf1940ec7a4bd07fe74a4b470f58c50c470b1e6078948dc0611b0b2ea17f58` |
| A090 | evidence/regression/modules/071-tests.test_transfer_ai_history/invocation.json — `evidence/regression/modules/071-tests.test_transfer_ai_history/invocation.json` | `ec938022ad844890529eae6ed193768f180196184ccc365a7924647d100f8072` |
| A091 | evidence/regression/modules/072-tests.test_transfer_ai_live_acceptance/invocation.json — `evidence/regression/modules/072-tests.test_transfer_ai_live_acceptance/invocation.json` | `44fcfa6988a1a9175f6162625bf9da6695f54a8bb52c97c0375471660707f838` |
| A092 | evidence/regression/modules/073-tests.test_transfer_analytics/invocation.json — `evidence/regression/modules/073-tests.test_transfer_analytics/invocation.json` | `3859b753c2b9248abcc4f893e2c9700cfcff0a4306811958ee86291d2335fd7f` |
| A093 | evidence/qualified/modules/tests.test_transfer_finance/raw/modules/000-tests.test_transfer_finance/invocation.json — `evidence/qualified/modules/tests.test_transfer_finance/raw/modules/000-tests.test_transfer_finance/invocation.json` | `cf3374c2f2f79bc51ae48e87bfa0e430693a0a47981028c8f74b225eea6bbbb4` |
| A094 | evidence/regression/modules/075-tests.test_transfer_finance_payments/invocation.json — `evidence/regression/modules/075-tests.test_transfer_finance_payments/invocation.json` | `e5e454fe6f6b2b9f584345d16eb225a16c31602e1c7b97cfe8735e6771f3eef9` |
| A095 | evidence/regression/modules/076-tests.test_transfer_lifecycle/invocation.json — `evidence/regression/modules/076-tests.test_transfer_lifecycle/invocation.json` | `3779559db8a86d90e93904d2b023e7f43753e389d8c8701ee722921d2c679902` |
| A096 | evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json — `evidence/regression/modules/077-tests.test_transfer_service_billing/invocation.json` | `f23960b2b1137f6b46c0aee32fc4ebb9126adbd671aa4ad016f16c1210b147cb` |
| A097 | evidence/regression/modules/078-tests.test_web_admission/invocation.json — `evidence/regression/modules/078-tests.test_web_admission/invocation.json` | `1d237ab42649c9c22679548faafb5832d59923617282dc40bbe9137551fb8aee` |
| A098 | evidence/regression/modules/079-tests.test_workshop_permissions_v30/invocation.json — `evidence/regression/modules/079-tests.test_workshop_permissions_v30/invocation.json` | `5453236830c72d2f700610cde16a64472b188778c293c93b4788faa6e361def8` |
| A099 | evidence/regression/modules/080-tests.test_workshop_provider_boundary/invocation.json — `evidence/regression/modules/080-tests.test_workshop_provider_boundary/invocation.json` | `360809f010333d86080fbdd6847f21e7f808fe969ee9fffbfca1693c72c05de4` |
| A100 | evidence/regression/modules/081-tests.test_workshop_timer/invocation.json — `evidence/regression/modules/081-tests.test_workshop_timer/invocation.json` | `4d5f64e5bc675833d8dcc18aac79a7776230c411f96fd6b825c32440a5f98783` |
| A101 | evidence/regression/modules/082-tests.test_workshop_timer_http/invocation.json — `evidence/regression/modules/082-tests.test_workshop_timer_http/invocation.json` | `0fc5be911c07fe1466ddad3075cff9ae663e92d159ee7654079910616673a95a` |
| A102 | evidence/regression/modules/083-tests.test_workshop_timer_native/invocation.json — `evidence/regression/modules/083-tests.test_workshop_timer_native/invocation.json` | `ce9397a6206bef3cdcae8961172c21101971f1211b8ae97cca72954562696972` |
| A103 | evidence/regression/modules/084-usage-reconciliation.test_operation_grants/invocation.json — `evidence/regression/modules/084-usage-reconciliation.test_operation_grants/invocation.json` | `5c5edb88a55faa6407057eb806006934c92b872238be94c01278e2728d2d87d5` |
| A104 | evidence/regression/modules/085-usage-reconciliation.test_operation_summary/invocation.json — `evidence/regression/modules/085-usage-reconciliation.test_operation_summary/invocation.json` | `8438c9c34903acd474b363ca54f27588d315ea2b2706b54372fd49fbea2ecda9` |
| A105 | evidence/regression/modules/086-usage-reconciliation.test_reconcile/invocation.json — `evidence/regression/modules/086-usage-reconciliation.test_reconcile/invocation.json` | `f88d024d3a9ff6279d00ee309b8e68cf4865c1ba3b0bc67625ba445030da2067` |
| A106 | evidence/regression/modules/087-native.assistant-preferences.test.mjs/invocation.json — `evidence/regression/modules/087-native.assistant-preferences.test.mjs/invocation.json` | `e727acf76625d8dfa4fd1fa777fac9d1fc88b31101093412dae8dd0e61fc8f9f` |
| A107 | evidence/regression/modules/088-native.capability-filter.test.mjs/invocation.json — `evidence/regression/modules/088-native.capability-filter.test.mjs/invocation.json` | `94b3b60f9f5d0356b843563051cc11b8e1507a7e0dcd250e7221d76a3ff33038` |
| A108 | evidence/regression/modules/089-native.chat-worker.test.mjs/invocation.json — `evidence/regression/modules/089-native.chat-worker.test.mjs/invocation.json` | `b7649491416a8456063236145d443aa5ba7afd22cf29a2c0cad118d385fddc6b` |
| A109 | evidence/regression/modules/090-native.guest-selector.test.mjs/invocation.json — `evidence/regression/modules/090-native.guest-selector.test.mjs/invocation.json` | `9e295cec8af0b76a78dfa5e4e2c5b1e659ad3de913923102d4fac5e971691622` |
| A110 | evidence/regression/modules/091-native.native-compaction.test.mjs/invocation.json — `evidence/regression/modules/091-native.native-compaction.test.mjs/invocation.json` | `b6163dc32b9850f286d2b17f4610c774cca4f0e09c84697f3492d14ad26ab439` |
| A111 | evidence/regression/modules/092-native.native-spill.test.mjs/invocation.json — `evidence/regression/modules/092-native.native-spill.test.mjs/invocation.json` | `5c80b90eaa85c6075ca8eb02da4014fb2aa55eeaf97273445a475bcfd00a36fd` |
| A112 | evidence/regression/modules/093-native.platform-mcp.test.mjs/invocation.json — `evidence/regression/modules/093-native.platform-mcp.test.mjs/invocation.json` | `ca3d8dc05d9c0bcd7c52e933b7093eacb274436376fb891428f922c5ea8cebca` |
| A113 | evidence/regression/modules/094-native.private-input.test.mjs/invocation.json — `evidence/regression/modules/094-native.private-input.test.mjs/invocation.json` | `3e5a31ab53e137a22b81c1d9c77a9c6acb880bbc2065a0d03b00814cc180e61a` |
| A114 | evidence/regression/modules/095-native.public-events.test.mjs/invocation.json — `evidence/regression/modules/095-native.public-events.test.mjs/invocation.json` | `78122648c6fcfd26d6f7f122ee7052b4f56901bf5a77d6146f9a3406f8424867` |
| A115 | evidence/regression/modules/096-native.timer-setup.test.mjs/invocation.json — `evidence/regression/modules/096-native.timer-setup.test.mjs/invocation.json` | `809b08e94733919678a3d48ed1e3638eb6dfc91852bdd0151ccc076152b01cee` |
| A116 | evidence/regression/modules/097-native.transfer-ai-contract.test.mjs/invocation.json — `evidence/regression/modules/097-native.transfer-ai-contract.test.mjs/invocation.json` | `5d8f8974232ab93f0a45373b3a222015a3327bb05daaf88cff8a24ea6aabb66c` |
| A117 | evidence/regression/modules/098-native.web-evidence.test.mjs/invocation.json — `evidence/regression/modules/098-native.web-evidence.test.mjs/invocation.json` | `36029784c7a0247830ca8778ca0e23301d545839678a00bed246c4a5e8b09a59` |
| A118 | evidence/regression/modules/100-gateway.server.test.mjs/invocation.json — `evidence/regression/modules/100-gateway.server.test.mjs/invocation.json` | `53fc7e4e55e15cf00fa538f97ed0298b80e17cb2ae91275f28b82bbf61d14dfd` |
| A119 | evidence/regression/modules/101-usage-reconciliation.test_gateway.mjs/invocation.json — `evidence/regression/modules/101-usage-reconciliation.test_gateway.mjs/invocation.json` | `a024f5d182d04e3dd134259d36937504d87336b0a3e2f05a301cda0fdd7b5367` |
| A120 | evidence/regression/modules/102-usage-reconciliation.test_operation_gateway.mjs/invocation.json — `evidence/regression/modules/102-usage-reconciliation.test_operation_gateway.mjs/invocation.json` | `9dd052ce8aee5e30d7c10fe5da107ce17a43ec833416b99393f1c465a970535d` |
| A121 | evidence/regression-qualified/result.json — `evidence/regression-qualified/result.json` | `bd9ced7d65b321c479c96431a0c0016cdca642979aa803d5cbb0bed52e1db1d1` |
| A122 | evidence/qualified/result.json — `evidence/qualified/result.json` | `c6f27edb3f79f4105b8db1e9bd351f20bdd605082a7f0698ccf9b0a93e1528e7` |
| A123 | evidence/supplementary-quota/manifest.json — `evidence/supplementary-quota/manifest.json` | `1662d0c66e74c2c717de52fffe8b63e012eca2f98caae4b8bbc07b266dc40e18` |
| A124 | evidence/stress/run-manifest.json — `evidence/stress/run-manifest.json` | `eb16e7a0724da036ce3aa843e897ee7259a45c6547d102144b3201307a7d555e` |
| A125 | evidence/stress/command-events.jsonl — `evidence/stress/command-events.jsonl` | `a87ad69f00d2084a283a25fb18b2d81b49284c20cc3d4c67fe3e4dcbecc756bc` |
| A126 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_accounting_browser/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_accounting_browser/command.json` | `8414593659b096d7eac9a4f8dcb90b030dd23f76c670a4535b8c6e31ad525545` |
| A127 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_agent_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_agent_ui/command.json` | `0a223e2956eb57f9be097a6239f99484aaa490d7663ae09495f9866a7a716406` |
| A128 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json` | `2707e314d614538b2839cd5c7b4f2d4a2c5b16c24590d0560798fd0dd24581aa` |
| A129 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json` | `dd7133812e69aa0eb5b5504f147625ff3950185e2ec4229d250b900c76c2a0ff` |
| A130 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_guest_ui/command.json` | `29daa3b56a423dbb762cbd0c958c045090e72b8c53d2ee7d0759fd3515fa4970` |
| A131 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_independent_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_independent_ui/command.json` | `09b869d80fddcbac7621fc8298198aa3e0465cb9f132f2b54a6cd863e6c5b7e4` |
| A132 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_layout/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_layout/command.json` | `e44a5b5a0f03b6fa0c9cfb075fb9b609cb7449d094aec9fe971ee2173317eae4` |
| A133 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_market_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_market_ui/command.json` | `9de79745a9d5b3497ab42457ec0ebc3010280d5272134ec437bebb7f06971014` |
| A134 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json` | `3d1dc9a586e08b570ac8cb8c496210df02ab04d4739374f8239d6e0306bb3cdc` |
| A135 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json` | `9e8c5c469a089a9face1f4119c647ba9e6e7f87809dc2f1e9b907188eb158cc8` |
| A136 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json` | `8c103e4bf91452caf003e036651aad597905f0e50299ed1030e35fe160461a2a` |
| A137 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v22_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v22_ui/command.json` | `e669c2a9baaaf48be32042d522ec854796d6915afdd6b03d07645306e2d4abe9` |
| A138 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v23_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v23_ui/command.json` | `cb56027ad1700976a18f52efe0e3f1b5f14f92827c64ca8ae4c4df5ce4d9685d` |
| A139 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v24_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_public_v24_ui/command.json` | `3cf99842c2976faf7b9308a53893831a682084de193eac5111ea263fa0387390` |
| A140 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_seasonal_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_seasonal_ui/command.json` | `00754d6002fea2feaa0666d8d6e7fda6f7f123c17d38117af312aa91df170538` |
| A141 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json` | `bc3e6eb30946d41b9b785b2167031ba0d685263f1b2b8a31a2b90aed53df6c64` |
| A142 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json` | `5c5673f044ae5beaf8dfacba11b46cc728c354b14386bea3b7fd35b300cfa209` |
| A143 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json` | `93951291db450e3364ac92c498fabb9a55b3b594e71c95c2a90280f2e01fad4c` |
| A144 | evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json` | `cd50bacbb5485c8b5bcc47555ee2a1876e03124f17b694514b987835b5ea611f` |
| A145 | evidence/browser/chromium/modules/tests.browser.test_service_price_form/command.json — `evidence/browser/chromium/modules/tests.browser.test_service_price_form/command.json` | `00b147c6bfb231eec12442cfd63b2ab3fa1181817a92f9212697eadea5d8afa9` |
| A146 | evidence/browser/chromium/modules/tests.browser.test_transfer_ai_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_transfer_ai_ui/command.json` | `44f6d597af63520046deccde5eebcba05300a1e2dd85ca5c3b0054587da5debc` |
| A147 | evidence/browser/chromium/modules/tests.browser.test_transfer_finance_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_transfer_finance_ui/command.json` | `5fa8a25be0561acb5f206fd64ea83ec624f1fbb34ed5860f8fc5c71c87e88e69` |
| A148 | evidence/browser/chromium/modules/tests.browser.test_transfer_shell_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_transfer_shell_ui/command.json` | `68450b37f13591de9b634a7e197257d6519b07a93f8c38bb1f343e04af8870b2` |
| A149 | evidence/browser/chromium/modules/tests.browser.test_workshop_permissions_v30_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_workshop_permissions_v30_ui/command.json` | `65d9846dd4553de0220b2d5b765241eab4ac3f90a3dcacd563bf78be0345a0a7` |
| A150 | evidence/browser/chromium/modules/tests.browser.test_workshop_timer_ui/command.json — `evidence/browser/chromium/modules/tests.browser.test_workshop_timer_ui/command.json` | `be0a4de7beab79dfac50888fe10ecf6d9ec55cc6c00bc2dfc3e91a3916d1b6c5` |
| A151 | evidence/browser/chromium/modules/tests.test_market_dual_browser/command.json — `evidence/browser/chromium/modules/tests.test_market_dual_browser/command.json` | `9a85eaa20d63d68ce5a0f4cc88e926ec463fc2bb923d7427251c81dd990f14aa` |
| A152 | evidence/browser/opera/modules/tests.browser.test_podmasterye_accounting_browser/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_accounting_browser/command.json` | `b940547e98b6efde19ad9ac0ed54635ade0aee20eef5a5b526d4680c364d9e40` |
| A153 | evidence/browser/opera/modules/tests.browser.test_podmasterye_agent_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_agent_ui/command.json` | `a3f484658486669d3e66b00351c3aa296945eb9bf47f2ffcf34eb25b96e7b9f0` |
| A154 | evidence/browser/opera/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_balance_v28_ui/command.json` | `9248643cd4b29cceec271242beb48e8f03698c07c3f47e59e9897a3122e36c0b` |
| A155 | evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_calculator_v25_ui/command.json` | `fe33f94054d9100e97cc256fbd512530ac7a06cf17feb3fb9590b8d6fabbc7df` |
| A156 | evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_guest_ui/command.json` | `2b191c302907f6d9d7151411a7d073c1525777f070d864b9fc58d148edf7cabe` |
| A157 | evidence/browser/opera/modules/tests.browser.test_podmasterye_independent_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_independent_ui/command.json` | `a95367a122d7f8cb064d6b192771911b78eb7903d205df865b512bef07db94b2` |
| A158 | evidence/browser/opera/modules/tests.browser.test_podmasterye_layout/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_layout/command.json` | `44818d9595321869dfbf89c152a7beaa047ad2dabfb9f1e593d284b85bc372c8` |
| A159 | evidence/browser/opera/modules/tests.browser.test_podmasterye_market_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_market_ui/command.json` | `ad5f41f6fa5f348b3d71412b903d9e19c115b9506d92f18b85670b20cf00809d` |
| A160 | evidence/browser/opera/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_owner_v18_ui/command.json` | `6e11d922da2aa9793188410ab603dbe8cfdf2a794ee022077a78a8e8130864d9` |
| A161 | evidence/browser/opera/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_profit_v26_ui/command.json` | `01a9a0de374c3d1f031b40e249adad9beb791ad5039a951dc1c3c36170f36719` |
| A162 | evidence/browser/opera/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_payment_v24_ui/command.json` | `de40edf1e1ac657ed9632349065e2cf18cef6b85341323bc03ee63c4da945480` |
| A163 | evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v22_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v22_ui/command.json` | `a4ea64a62e08e883be599945a7181199dd15bdaca8d138a9c22d365064e51b60` |
| A164 | evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v23_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v23_ui/command.json` | `88d04fb345349da662ef574da30f489c52cd7307e84ef120adadf27a55a215bc` |
| A165 | evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v24_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_public_v24_ui/command.json` | `caed30fcc411b8da7a707908a1edcbd265d8875269a7ec1bad3ff73d3f2f3e91` |
| A166 | evidence/browser/opera/modules/tests.browser.test_podmasterye_seasonal_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_seasonal_ui/command.json` | `df79c394ae473c10fa7f5039b2bd7731c34235e6ab01c545fcde983fa15e98a9` |
| A167 | evidence/browser/opera/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_single_workshop_v20_ui/command.json` | `440117c9abc13cb42e4db9d6638643c89f84b67751fdbb32d3fef25cf7c653bb` |
| A168 | evidence/browser/opera/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_sliders_v27_ui/command.json` | `3d8238c1650721079796b44904564e58220ad2ea8f9949b985a02d012e20c2d8` |
| A169 | evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_market_ui/command.json` | `439601965e6abcce7ee3a6add893943c604de9e9ea246ac8ad76a134ead2dbc2` |
| A170 | evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_podmasterye_yandex_sales_ui/command.json` | `d5740367f1afc71b71b87af3e1ef607ac077c076264e865deee94280aae87d7a` |
| A171 | evidence/browser/opera/modules/tests.browser.test_service_price_form/command.json — `evidence/browser/opera/modules/tests.browser.test_service_price_form/command.json` | `75a833cfdc8634cefab080b539d1b4d16963059bac0fdaae2b5312f871a6f5ee` |
| A172 | evidence/browser/opera/modules/tests.browser.test_transfer_ai_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_transfer_ai_ui/command.json` | `baaa525c15fc043fe1e8e1ee14ee4b72c7ab93f561cc1ca0bd97b249c716d76a` |
| A173 | evidence/browser/opera/modules/tests.browser.test_transfer_finance_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_transfer_finance_ui/command.json` | `0a7c0a13ee7a1c401a518efbfc6605289b6c7e536cb5fcf3005a116fe77f4e08` |
| A174 | evidence/browser/opera/modules/tests.browser.test_transfer_shell_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_transfer_shell_ui/command.json` | `6134988997efcc5f52fed5b74bfaa7bea0088b3e6c6f0dc95d5656f3986b4772` |
| A175 | evidence/browser/opera/modules/tests.browser.test_workshop_permissions_v30_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_workshop_permissions_v30_ui/command.json` | `558af20acaad76bdba9833de3c65c819032f61dc9f8232b7d7e6cb789598d6ef` |
| A176 | evidence/browser/opera/modules/tests.browser.test_workshop_timer_ui/command.json — `evidence/browser/opera/modules/tests.browser.test_workshop_timer_ui/command.json` | `23ad92f80c5a5db13c2a95bb8adacc422c1cbb4307b8e7accedf77e5bbae6e86` |
| A177 | evidence/browser/opera/modules/tests.test_market_dual_browser/command.json — `evidence/browser/opera/modules/tests.test_market_dual_browser/command.json` | `547ef077eb14a403a40c853fc39e6c9259c5e7423c18a4cb5921d0f99cb9b0f6` |
| A178 | evidence/rollback-6fa/old-invocation.json — `evidence/rollback-6fa/old-invocation.json` | `63d7ab185be68ca3b6dcd6941d8ac72408ea2058c470dc392e4802b2d0d3e5db` |
| A179 | evidence/rollback-production/invocation.json — `evidence/rollback-production/invocation.json` | `dd4dd3fb07a6ebdb41c0f75846b86ef01207c1ae1ce42780fcf62c655543dbff` |
| A180 | evidence/delivery-assembly.json — `evidence/delivery-assembly.json` | `f8fd24e6624e3fc375b7998ff83b81a6c72eea12cc249d8aa1a0f5b76152af84` |
| A181 | evidence/mc50-delivery-review.json — `evidence/mc50-delivery-review.json` | `32d7e6a572db43e44082261fe726cbed4bed5e9edc5866a78243244fc2888b79` |
