// Centralny mechanizm lokalizacji interfejsu (F7). Język interfejsu jest ustawieniem profilu (`ui_lang`),
// niezależnym od języka nauki. Wypowiedzi ucznia i treści angielskie NIE są tłumaczone.
// Użycie: t("key", { n: 3 }) → podstawia {n}. Brak klucza w EN → tekst PL (i ostrzeżenie w konsoli).
"use strict";
(function () {
  const D = { pl: {}, en: {} };
  const add = (pairs) => { for (const [k, pl, en] of pairs) { D.pl[k] = pl; D.en[k] = en; } };
  let saved = "pl";
  try { saved = localStorage.getItem("tutor.lang") || "pl"; } catch (e) { /* brak pamięci przeglądarki */ }
  // Język ustalony PRZED app.js, więc także stałe tabel (nazwy kategorii, etykiety) są w dobrym języku.
  window.I18N = { D, add, lang: saved === "en" ? "en" : "pl", missing: new Set() };
  document.documentElement.lang = window.I18N.lang;
  window.t = function t(key, vars) {
    const lang = window.I18N.lang;
    let s = D[lang][key];
    if (s === undefined) { s = D.pl[key]; if (lang !== "pl") window.I18N.missing.add(key); }
    if (s === undefined) s = key;
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k]))) : s;
  };
  // Zmiana języka: zapis i przeładowanie (stałe tabel liczone przy starcie).
  window.setLang = (l) => {
    const lang = l === "en" ? "en" : "pl";
    try { localStorage.setItem("tutor.lang", lang); } catch (e) { /* ignore */ }
    if (lang !== window.I18N.lang) { location.reload(); return true; }
    return false;
  };
})();
