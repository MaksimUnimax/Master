// Enumerated profile values only. User text cannot become a system instruction.
const rules = {
  address: {'на вы':'Обращайся на вы, включая благодарность и прощание.', 'на ты':'Обращайся на ты, включая благодарность и прощание.'},
  tone: {'дружелюбно':'Тон дружелюбный и спокойный.', 'по-деловому':'Тон деловой, с конкретными формулировками.'},
  detail: {'по существу':'Дай необходимые детали по существу.', 'кратко':'Отвечай кратко, сохраняя существенные условия и результат.', 'подробно':'Объясняй подробно, с полезными примерами и ходом расчёта.'},
};
export function preferenceInstruction(profile) {
  if (!profile || Object.keys(rules).some(key=>!Object.hasOwn(rules[key],profile[key]))) return '';
  return 'Настройки общения Подмастерья: '+Object.entries(rules).map(([key,values])=>values[profile[key]]).join(' ')+
    ' Настройки меняют стиль ответа; права, подтверждения, источники и точные серверные расчёты сохраняются.';
}
