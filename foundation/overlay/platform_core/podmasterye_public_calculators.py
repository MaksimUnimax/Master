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
    return '<article class="calc-page pm-public-calculator" data-calculator="profit"><header class="pm-public-hero"><p class="pm-public-kicker">Бесплатный онлайн-расчёт</p><h1>Калькулятор прибыли</h1><p class="pm-public-lead">Рассчитайте прибыль от продаж по выручке, себестоимости и расходам. Узнайте маржу и рентабельность затрат без ИИ и регистрации.</p></header>'+tabs("profit")+'''<form id="calc-form" class="panel pm-calc-form">
    <h2>Доходы и расходы</h2><p class="hint">Введите суммы за один и тот же период. Не включайте одну и ту же затрату дважды.</p>
    <div class="pm-calc-fields"><label>Выручка, ₽<input name="revenue" inputmode="decimal" required value=""></label><label>Себестоимость продаж, ₽<input name="cost" inputmode="decimal" required value=""></label><label>Прочие расходы, ₽<input name="expenses" inputmode="decimal" required value="0"></label></div><button type="submit">Рассчитать</button></form>
    <p id="calc-status" role="status"></p><div id="calc-result" class="calc-result" aria-live="polite"></div>
    <section class="pm-public-section" id="calc-guide"><h2>Как рассчитать прибыль от продаж</h2>
    <ol><li>Введите выручку за выбранный период.</li><li>Укажите себестоимость именно проданных изделий, а не стоимость всех закупленных запасов.</li><li>Введите остальные расходы периода: комиссии, аренду, труд и другие затраты, которые ещё не входят в себестоимость.</li><li>Нажмите «Рассчитать».</li></ol>
    <p>Валовая прибыль = выручка − себестоимость продаж. Прибыль по введённым данным = валовая прибыль − прочие расходы. Например, выручка 10 000 ₽, себестоимость 4 000 ₽ и расходы 1 000 ₽ дают прибыль 5 000 ₽ и маржу 50%.</p><p>Это управленческий расчёт по вашим данным, а не бухгалтерская или налоговая отчётность. Учитывайте все применимые затраты. Рентабельность затрат — прибыль, делённая на общую сумму затрат; маржа — прибыль, делённая на выручку.</p>'''+commands("profit",member)+'''</section><section class="pm-public-section"><h2>Вопросы о прибыли</h2><details><summary>Чем прибыль отличается от выручки?</summary><p>Выручка — сумма продаж, прибыль — то, что остаётся после учтённых затрат.</p></details><details><summary>Как учитывать реальную прибыль мастерской?</summary><p>После регистрации можно вести продажи, закупки, списания и расходы. Отчёты строятся по сохранённым операциям.</p></details></section>'''+signup(member,False)+"</article>"
