// Centralny mechanizm lokalizacji interfejsu (F7). Język interfejsu jest ustawieniem profilu (`ui_lang`),
// niezależnym od języka nauki. Wypowiedzi ucznia i treści angielskie NIE są tłumaczone.
// Użycie: t("key", { n: 3 }) → podstawia {n}. Brak klucza w EN → tekst PL (i ostrzeżenie w konsoli).
"use strict";
(function () {
  const D = { pl: {}, en: {} };
  const add = (pairs) => { for (const [k, pl, en] of pairs) { D.pl[k] = pl; D.en[k] = en; } };
  window.I18N = { D, add, lang: "pl" };
  window.t = function t(key, vars) {
    const lang = window.I18N.lang;
    let s = D[lang][key];
    if (s === undefined) { s = D.pl[key]; if (lang !== "pl") console.warn("i18n missing:", key); }
    if (s === undefined) return key;
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k]))) : s;
  };
  window.setLang = (l) => { window.I18N.lang = D[l] ? l : "pl"; document.documentElement.lang = window.I18N.lang; };
})();
