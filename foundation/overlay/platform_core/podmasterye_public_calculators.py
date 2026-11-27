"""Server-rendered public calculators with concise SEO and local command guidance."""
from html import escape
from .podmasterye_guest_calculator import matrix
from .podmasterye_import import CALC_UNITS

def commands(panel,member=False):
    if member:return ''
    entries="".join('<li><button type="button" class="pm-calc-command secondary" data-calc-command="'+escape(r["example"],quote=True)+'">'+escape(r["example"])+'</button></li>' for r in matrix() if r["panel"]==panel)
    return '<details class="pm-calc-commands"><summary>Как управлять калькулятором через Подмастерье</summary><p>Нажмите пример команды, чтобы вставить его в чат, или напишите свою команду по этому шаблону. Расчёт выполняется без ИИ. Гостевой чат ограничен 12 сообщениями, ручной калькулятор работает независимо от лимита.</p><ul>'+entries+'</ul></details>'

def tabs(active):
    from .podmasterye_public_pages import link
    return '<div class="pm-calc-tabs" aria-label="Выбор калькулятора">'+link("calculator","Себестоимость", "pm-public-primary" if active=="calculator" else "pm-public-secondary")+link("profit","Прибыль","pm-public-primary" if active=="profit" else "pm-public-secondary")+'</div>'

def signup(member,save=True):
    from .podmasterye_public_pages import link
    if member:
        return '<div class="pm-calc-registration"><p>Перенесите расчёт в свою мастерскую, чтобы вести учёт материалов, закупок и продаж.</p><a href="/app/" class="pm-public-primary">Моя мастерская</a></div>'
    return '<div class="pm-calc-registration"><h2>От расчёта к учёту мастерской</h2><p>Зарегистрируйтесь, чтобы сохранять изделия и рецептуры, учитывать склад, закупки, выпуск и продажи, видеть прибыль за выбранный период. Сам калькулятор остаётся бесплатным.</p>'+link("register","Создать аккаунт","pm-public-primary")+'</div>'

def cost_content(member):
    units="".join("<option>"+escape(u)+"</option>" for u in CALC_UNITS)
    return '<article class="calc-page pm-public-calculator" data-calculator="calculator"><header class="pm-public-hero"><p class="pm-public-kicker">Бесплатный онлайн-расчёт</p><h1>Калькулятор себестоимости изделия</h1><p class="pm-public-lead">Рассчитайте себестоимость продукции, стоимость материалов и труда, прибыль и наценку. Без регистрации и расхода монет.</p></header>'+tabs("calculator")+'''<form id="calc-form" class="panel pm-calc-form">
    <label>Название изделия<input name="product_name" required maxlength="120" placeholder="Например, браслет"></label>
    <h2>Материалы</h2><p class="hint">Укажите цену всей упаковки и сколько единиц расходуется на одно изделие. Для цены за единицу оставьте упаковку равной 1.</p>
    <div id="calc-rows"></div><template id="calc-row-template"><div class="calc-line pm-calc-material">
    <label class="pm-calc-name">Материал<input name="name" required maxlength="120" placeholder="Бусины"></label>
    <label>Единица<select name="unit">'''+units+'''</select></label><label>В упаковке<input name="pack_quantity" inputmode="decimal" value="1" required></label>
    <label>Цена упаковки, ₽<input name="price" inputmode="decimal" required></label><label>Расход на изделие<input name="quantity" inputmode="decimal" value="1" required></label>
    <button type="button" data-remove-material class="secondary compact" aria-label="Удалить материал">×</button></div></template>
    <button id="calc-add" type="button" class="secondary">Добавить материал</button><h2>Цена и труд</h2>
    <div class="pm-calc-fields"><label>Цена продажи, ₽<input name="sale_price" inputmode="decimal" required value="0"></label>
    <label>Время изготовления, мин<input name="minutes" inputmode="decimal" required value="0"></label>
    <label>Стоимость часа, ₽<input name="hourly_rate" inputmode="decimal" required value="0"></label></div>
    <button type="submit">Рассчитать</button></form><p id="calc-status" role="status"></p>
    <div id="calc-result" class="calc-result" aria-live="polite"></div>
    <button id="calc-save" type="button" disabled>Сохранить в мастерскую</button>
    <p class="hint">Расчёт не меняет складские остатки. Для сохранения изделия войдите или зарегистрируйтесь; ставку труда задайте в настройках мастерской.</p>
    <section class="pm-public-section" id="calc-guide"><h2>Как рассчитать себестоимость продукции</h2>
    <ol><li>Введите название изделия.</li><li>Добавьте все материалы. Количество в упаковке и расход указывайте в одной единице измерения.</li><li>Введите цену продажи, время изготовления и стоимость часа труда.</li><li>Нажмите «Рассчитать». При изменении данных результат обновится автоматически.</li></ol>
    <p>Например, упаковка из 400 бусин стоит 800 ₽, на браслет уходит 20 бусин. Себестоимость бусин: 800 ÷ 400 × 20 = 40 ₽. Если работа занимает 30 минут при ставке 300 ₽/час, труд стоит 150 ₽. Сумма этих затрат — 190 ₽.</p>
    <p>Калькулятор показывает материалы, труд, себестоимость по введённым данным, прибыль, маржу и наценку. Для полной экономики необходимо также учитывать упаковку, брак, накладные расходы, удержания и налоги, если они применимы. В мастерской доступны отдельные операции и отчёты по реальным расходам.</p>'''+commands("calculator",member)+'''</section><section class="pm-public-section"><h2>Вопросы о расчёте себестоимости</h2><details><summary>Чем себестоимость изделия отличается от цены продажи?</summary><p>Себестоимость — затраты на изготовление изделия. Цена продажи включает эти затраты и возможную прибыль.</p></details><details><summary>Можно ли рассчитывать изделия ручной работы?</summary><p>Да. Укажите фактический расход материалов и стоимость труда — для украшений, свечей, шитья, кондитерских изделий и других товаров.</p></details><details><summary>Нужна ли регистрация?</summary><p>Нет, для расчёта не нужна. Аккаунт нужен для сохранения изделий, рецептур и полноценного учёта.</p></details></section>'''+signup(member)+"</article>"

def profit_content(member):
    def field(key,label,value="",placeholder=""):
        return f'<label>{escape(label)}<input name="{key}" inputmode="{"numeric" if key=="units" else "decimal"}" required value="{escape(value,quote=True)}" placeholder="{escape(placeholder,quote=True)}"></label>'
    units=field("units","Продано изделий, шт.","1")+field("unit_price","Цена продажи, ₽/шт.","","500")+field("unit_cost","Себестоимость, ₽/шт.","","180")
    selling=field("commission_percent","Комиссия и эквайринг, %","0")+field("delivery_unit","Доставка, ₽/шт.","0")+field("packing_unit","Упаковка, ₽/шт.","0")+field("other_unit","Другие затраты, ₽/шт.","0")
    fixed=field("advertising","Реклама, ₽","0")+field("fixed_expenses","Постоянные расходы, ₽","0")+field("taxes","Налоги, ₽","0")
    period=field("revenue","Выручка, ₽","","10000")+field("cost","Себестоимость продаж, ₽","","4000")+field("expenses","Прочие расходы, ₽","0")
    return '<article class="calc-page pm-public-calculator pm-profit-page" data-calculator="profit"><header class="pm-public-hero"><p class="pm-public-kicker">Экономика продаж · бесплатно</p><h1>Калькулятор прибыли</h1><p class="pm-public-lead">Узнайте, сколько заработаете на продаже изделия или партии. Учитывайте себестоимость, комиссии и остальные расходы.</p></header>'+tabs("profit")+f'''<div class="pm-profit-modes" role="group" aria-label="Способ расчёта">
    <button type="button" data-profit-mode="units" aria-pressed="true">По изделиям</button><button type="button" data-profit-mode="period" aria-pressed="false">По выручке</button></div>
    <div id="profit-summary" class="pm-profit-summary" aria-live="polite">
    <span class="pm-profit-label">Прибыль по введённым данным</span><strong id="profit-main-value">—</strong>
    <div class="pm-profit-kpis"><div><span>Выручка</span><strong id="profit-summary-revenue">—</strong></div><div><span>Все затраты</span><strong id="profit-summary-cost">—</strong></div><div><span>Маржа</span><strong id="profit-summary-margin">—</strong></div><div><span id="profit-summary-extra-label">Прибыль на штуку</span><strong id="profit-summary-extra">—</strong></div></div>
    <div id="profit-bar" class="pm-profit-bar" hidden><div id="profit-bar-cost"></div><div id="profit-bar-gain"></div></div><div id="profit-bar-caption" class="hint" hidden></div></div>
    <form id="calc-form" class="panel pm-calc-form pm-profit-form">
    <fieldset data-profit-fields="units"><div class="pm-profit-section-head"><h2>Продажи</h2><button type="button" id="profit-example" class="secondary">Заполнить пример</button></div>
    <div class="pm-calc-fields pm-profit-sales">{units}</div>
    <button type="button" id="profit-import-cost" class="secondary">Взять себестоимость из калькулятора</button>
    <p class="hint">В себестоимость включите материалы и труд. Не учитывайте их второй раз в расходах ниже.</p>
    <div class="pm-profit-section-head"><h2>Расходы на продажу</h2><span>На одно изделие</span></div>
    <div class="pm-calc-fields">{selling}</div><p class="hint">Комиссия рассчитывается от выручки. Доставку и упаковку указывайте только если они не входят в себестоимость.</p>
    <div class="pm-profit-section-head"><h2>Расходы за период</h2><span>Общая сумма</span></div>
    <div class="pm-calc-fields">{fixed}</div><p class="hint">Введите расходы на весь указанный объём продаж. Налоги — ваша оценка; налоговый режим автоматически не определяется.</p></fieldset>
    <fieldset data-profit-fields="period" hidden disabled><h2>Итоги за период</h2><p class="hint">Если все суммы уже известны, используйте этот режим. Введите их за один и тот же период, без двойного учёта затрат.</p><div class="pm-calc-fields">{period}</div></fieldset>
    <button type="submit">Рассчитать прибыль</button></form>
    <p id="calc-status" role="status"></p><div id="calc-result" class="calc-result" aria-live="polite"></div>
    <section class="pm-public-section" id="calc-guide"><h2>Как рассчитать прибыль от продаж</h2>
    <p>Прибыль = выручка − себестоимость проданных изделий − расходы на продажу − расходы за период. При расчёте по изделиям выручка и себестоимость автоматически умножаются на количество. Комиссия считается от выручки.</p>
    <p>Пример: 100 изделий по 500 ₽, себестоимость 180 ₽/шт., комиссия 10%, доставка 40 ₽/шт., упаковка 10 ₽/шт., реклама 2 000 ₽ и постоянные расходы 3 000 ₽. Выручка — 50 000 ₽, затраты — 33 000 ₽, прибыль — 17 000 ₽, маржа — 34%. Налоги в примере не учтены.</p>
    <p>Точка безубыточности показывает минимальный объём продаж и минимальную цену при текущих условиях. Расчёт предполагает неизменные цену, удельные расходы, процент комиссии и заданные расходы за период. Это оценка, а не налоговая отчётность.</p>'''+commands("profit",member)+'''</section><section class="pm-public-section"><h2>Частые вопросы о прибыли</h2><details><summary>Чем прибыль отличается от выручки?</summary><p>Выручка — сумма продаж, прибыль — то, что остаётся после всех введённых затрат.</p></details><details><summary>Чем маржа отличается от рентабельности?</summary><p>Маржа — прибыль в процентах от выручки, рентабельность затрат — прибыль в процентах от затрат. При нулевом знаменателе показатель не определён.</p></details><details><summary>Как вести реальную прибыль мастерской?</summary><p>После регистрации можно вести закупки, выпуск, продажи и расходы. Отчёты строятся по проведённым операциям.</p></details></section>'''+signup(member,False)+"</article>"
