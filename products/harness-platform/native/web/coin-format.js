(() => {
  'use strict';
  const format = value => {
    const text = String(value ?? '');
    if (!/^-?\d{1,30}(?:\.\d{1,12})?$/.test(text)) return '—';
    const negative = text.startsWith('-'), [whole, part = ''] = text.replace('-', '').split('.');
    const fraction = part.padEnd(3, '0');
    const cents = BigInt(whole) * 100n + BigInt(fraction.slice(0, 2)) + (fraction[2] >= '5' ? 1n : 0n);
    return (negative && cents ? '−' : '') + (cents / 100n).toLocaleString('ru-RU') + ',' + String(cents % 100n).padStart(2, '0');
  };
  window.MasterCoins = Object.freeze({format});
})();
