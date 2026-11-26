// AI Language Tutor — interfejs lokalny. Cała dydaktyka jest w Pythonie; tu tylko wyświetlanie i polecenia.
"use strict";

const TOKEN = document.querySelector('meta[name="tutor-token"]').content;
const S = { pid: null, profiles: [], system: null, settings: null, seq: 0, poll: null, session: null, catalog: null };
const { icon, pxText, mascot, mascotHead, badgeArt, scene } = window.PX;
// Imię maskotki NIE jest zatwierdzone (decyzja właściciela) — do tego czasu neutralnie „Nauczyciel”.
const MASCOT_NAME = t("Nauczyciel");

// ---------- narzędzia ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Tutor-Token": TOKEN },
    body: JSON.stringify(body),
  };
  let r;
  try { r = await fetch(path, opt); } catch (e) { throw new Error(t("Brak połączenia z aplikacją. Czy okno terminala z `python main.py --gui` nadal działa?")); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || t("Błąd {s}", { s: r.status }));
  return data;
}
const q = (path, extra = "") => api(`${path}?pid=${S.pid}${extra}`);

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 7000);
}

function fmtDate(s) { return s ? s.replace("T", " ").slice(0, 16) : "—"; }
function fmtDay(s) { return s ? s.slice(0, 10) : "—"; }
function fmtMin(sec) { const m = Math.round((sec || 0) / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; }
const go = (hash) => { location.hash = hash; };

// ---------- komponenty ----------
function btn(label, onclick, cls = "", ic = null) { return h("button", { class: `btn ${cls}`, onclick, type: "button" }, ic ? icon(ic, 18) : null, label); }
function card(title, ...kids) { return h("section", { class: "card" }, title ? h("h2", { class: "card-title" }, title) : null, ...kids); }
function cardT(ic, title, more, ...kids) {
  return h("section", { class: "card" }, h("h2", { class: "card-title" }, ic ? icon(ic, 22) : null, title, more), ...kids);
}
function chip(text, cls = "") { return h("span", { class: `chip ${cls}` }, text); }
function bar(value, max, label, cls = "") {
  const pct = max ? Math.max(0, Math.min(100, Math.round(100 * value / max))) : 0;
  const fill = h("span", { class: "bar-fill" });
  fill.style.width = pct + "%";
  return h("span", { class: `bar ${cls}`, role: "progressbar", "aria-valuemin": 0, "aria-valuemax": max, "aria-valuenow": Math.min(value, max), "aria-label": label || `${value}/${max}` }, fill);
}
function pageHead(eyebrow, title, sub, ...actions) {
  return h("header", { class: "page-head" },
    h("div", {}, eyebrow ? h("span", { class: "eyebrow" }, eyebrow) : null,
      h("h1", {}, h("span", { class: "sr-only" }, title), pxText(title, 4)),
      sub ? h("p", {}, sub) : null),
    actions.length ? h("div", { class: "row" }, ...actions) : null);
}
// Bezpieczne, minimalne formatowanie wyjaśnień (nagłówki ##, listy -, `kod`, **pogrubienie**) — bez innerHTML.
function rich(text) {
  const box = h("div", { class: "rich" });
  let list = null;
  const inline = (t) => t.split(/(`[^`]+`|\*\*[^*]+\*\*)/).map((part) => (part.length > 2 && part.startsWith("`") && part.endsWith("`") ? h("code", {}, part.slice(1, -1))
    : part.length > 4 && part.startsWith("**") && part.endsWith("**") ? h("strong", {}, part.slice(2, -2)) : part));
  for (const line of text.split("\n")) {
    const m = line.match(/^(#{1,3})\s+(.*)$/);
    if (m) { list = null; box.append(h(m[1].length === 1 ? "h3" : "h4", {}, inline(m[2]))); continue; }
    if (/^\s*[-•]\s+/.test(line)) { if (!list) { list = h("ul"); box.append(list); } list.append(h("li", {}, inline(line.replace(/^\s*[-•]\s+/, "")))); continue; }
    list = null;
    if (line.trim()) box.append(h("p", {}, inline(line)));
  }
  return box;
}
function note(text, cls = "") { return h("p", { class: `note ${cls}` }, text); }
function table(head, rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "grid" }, h("thead", {}, h("tr", {}, head.map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))));
}
function seg(label, options, value, onchange) {
  const box = h("div", { class: "seg", role: "group", "aria-label": label });
  box.value = value;
  const draw = () => box.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === String(box.value))));
  for (const [v, l] of options) box.append(h("button", { type: "button", "data-v": v, onclick: () => { box.value = v; draw(); onchange && onchange(v); } }, l));
  draw();
  return box;
}
function stat(label, value) { return h("div", { class: "stat" }, h("span", {}, label), h("strong", {}, String(value))); }
function fixLine(span, fix) { return h("span", { class: "fix", lang: "en" }, h("s", {}, span), " → ", h("ins", {}, fix)); }

// ---------- nazwy ----------
const AREA_PL = { grammar: t("gramatyka"), vocabulary: t("słownictwo"), speaking: t("mówienie"), reading: t("czytanie"), listening: t("słuchanie"), writing: t("pisanie") };
const areaPl = (a) => AREA_PL[a] || a;
const CAT_PL = {
  tense: t("Czasy"), "tense.present_simple": "Present simple", "tense.present_continuous": "Present continuous",
  "tense.past_simple": "Past simple", "tense.past_continuous": "Past continuous", "tense.present_perfect": "Present perfect",
  "tense.past_perfect": "Past perfect", "tense.future": t("Przyszłość"), "tense.sequence": t("Następstwo czasów"), aspect: t("Aspekt czasownika"),
  agreement: t("Zgodność form"), "agreement.subject_verb": t("Zgodność podmiotu z orzeczeniem"), "agreement.number": t("Liczba pojedyncza/mnoga"),
  article: t("Przedimki"), "article.missing": t("Brak przedimka"), "article.wrong": t("Zły przedimek"), "article.extra": t("Zbędny przedimek"),
  determiner: t("Określniki"), "determiner.quantifier": t("Kwantyfikatory (much/many…)"), "determiner.possessive": t("Zaimki dzierżawcze"),
  preposition: t("Przyimki"), "preposition.time": t("Przyimki czasu"), "preposition.place": t("Przyimki miejsca"), "preposition.dependent": t("Stałe przyimki"),
  word_order: t("Szyk zdania"), "word_order.question": t("Szyk pytania"), "word_order.adverb": t("Miejsce przysłówka"), "word_order.subordinate": t("Pytania zależne"),
  word_choice: t("Dobór słowa"), "word_choice.false_friend": t("Fałszywi przyjaciele"), "word_choice.confusable": t("Słowa mylone (make/do…)"),
  collocation: t("Kolokacje"), "collocation.verb_noun": t("Czasownik + rzeczownik"), "collocation.adj_noun": t("Przymiotnik + rzeczownik"),
  morphology: t("Forma słowa"), "morphology.irregular_past": t("Czasowniki nieregularne"), "morphology.plural": t("Liczba mnoga"),
  "morphology.comparative": t("Stopniowanie"), "morphology.word_form": t("Część mowy"), register: t("Styl wypowiedzi"), "register.formality": t("Formalność"),
  spelling: t("Pisownia"), punctuation: t("Interpunkcja"), capitalization: t("Wielkie litery"), omission: t("Brakujące słowo"),
  "omission.subject": t("Brak podmiotu"), "omission.auxiliary": t("Brak operatora (do/does/did…)"), "omission.copula": t("Brak to be"),
  l1_calque: t("Kalka z polskiego"), "l1_calque.make_photo": t("make a photo (kalka)"), "l1_calque.have_years": t("I have 25 years (kalka)"),
  "l1_calque.explain_me": t("explain me (kalka)"),
};
const catPl = (c) => CAT_PL[c] || CAT_PL[(c || "").split(".")[0]] || c;
async function catalog() {
  if (!S.catalog) S.catalog = (await q("/api/lessons")).catalog;
  return S.catalog;
}
// EN: paczka treści ma opisy celów tylko po polsku — pokazujemy nazwę umiejętności z jej identyfikatora.
const skillEn = (id) => { const s = String(id).split(".").pop().replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); };
const skillName = (c) => (I18N.lang === "en" ? skillEn(c.skill_id) : c.can_do_pl);
const skillPl = (id) => (I18N.lang === "en" ? skillEn(id) : (S.catalog || []).find((c) => c.skill_id === id)?.can_do_pl || id);
const rpContext = (tp) => (I18N.lang === "en" && tp.learner ? `You are ${tp.learner}. The tutor plays ${tp.role}.` : tp.context_pl);

// ---------- nawigacja ----------
const NAV = [
  [t("Nauka"), [["home", "Start", "home"], ["chat", "Quick Chat", "chat"], ["lesson", t("Lekcje"), "lesson"], ["review", t("Powtórki"), "review"]]],
  [t("Rozwój"), [["weak", t("Słabe strony"), "weak"], ["placement", t("Diagnoza"), "level"], ["exam", t("Egzaminy"), "exam"]]],
  [t("Ty"), [["progress", t("Postępy"), "progress"], ["achievements", t("Osiągnięcia"), "trophy"], ["settings", t("Ustawienia"), "gear"]]],
];

function renderNav(active) {
  const nav = document.getElementById("nav");
  const live = S.session && S.session.running && active !== "session"
    ? h("a", { class: "nav-live", href: "#/session" }, t("Trwa: {k} — wróć", { k: KIND_TITLE[S.session.kind] || t("sesja") })) : null;
  nav.replaceChildren(...[live, ...NAV.flatMap(([group, items]) => [h("div", { class: "nav-group" }, group),
    ...items.map(([id, label, ic]) => h("a", { href: `#/${id}`, class: "nav-item", "aria-current": id === active ? "page" : null }, icon(ic, 20), label))])].filter(Boolean));
}

function setStatus() {
  const st = S.system;
  const who = S.profiles.find((p) => p.id === S.pid);
  const sys = [];
  if (st) {
    sys.push(h("div", { class: `sys ${st.ollama ? "ok" : "bad"}` }, st.ollama ? `Model: ${S.settings?.values?.chat_model || st.roles.conversation || "Ollama"}` : t("Ollama nie odpowiada")));
    sys.push(h("div", { class: `sys ${st.kokoro ? "ok" : "bad"}` }, st.kokoro ? t("Głos: gotowy") : t("Głos: brak plików Kokoro")));
    sys.push(h("div", { class: `sys ${st.audio_error ? "bad" : "ok"}` }, st.audio_error ? t("Mikrofon: niedostępny") : t("Mikrofon: dostępny")));
  }
  document.getElementById("status").replaceChildren(...[
    who ? h("div", { class: "profile-chip" }, h("div", { class: "avatar", "aria-hidden": "true" }, who.name.slice(0, 1).toUpperCase()),
      h("div", {}, h("strong", {}, who.name), h("span", {}, t("profil ucznia"))), h("a", { href: "#/profiles" }, t("Zmień"))) : null,
    h("div", { class: "sys-list" }, sys)].filter(Boolean));
}

function voiceAvailable() { return S.system && S.system.kokoro && !S.system.audio_error; }
function defaultTextMode() { return !voiceAvailable() || S.settings?.values?.io_mode === "text"; }

// ---------- profile ----------
async function loadProfiles() {
  const r = await api("/api/profiles");
  S.profiles = r.profiles;
  let saved = null;
  try { saved = Number(localStorage.getItem("tutor.pid")); } catch (e) { /* brak pamięci przeglądarki */ }
  const ids = S.profiles.map((p) => p.id);
  S.pid = ids.includes(saved) ? saved : ids.includes(r.last) ? r.last : (ids[0] ?? null);
}
function choosePid(id) {
  S.pid = id; S.settings = null;
  try { localStorage.setItem("tutor.pid", String(id)); } catch (e) { /* ignore */ }
  api("/api/profiles/select", { pid: id }).catch(() => {});
}
function createForm() {
  const name = h("input", { type: "text", maxlength: 40, placeholder: t("np. Ola"), "aria-label": t("Nazwa nowego profilu") });
  const create = async () => {
    try {
      const p = await api("/api/profiles", { name: name.value }); await loadProfiles(); choosePid(p.id);
      if (location.hash === "#/home") route(); else go("#/home");
    } catch (e) { toast(e.message); }
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  return h("div", { class: "row" }, name, btn(t("Utwórz profil"), create, "primary"));
}
async function screenProfiles(main) {
  main.append(pageHead(t("Kto się uczy?"), t("Profile"), t("Każdy profil ma osobną historię, postępy, osiągnięcia i ustawienia.")),
    S.profiles.length ? h("div", { class: "profiles" }, S.profiles.map((p) => h("button", { type: "button", class: "profile-card", "aria-current": p.id === S.pid ? "true" : null,
      onclick: () => { choosePid(p.id); go("#/home"); } }, h("div", { class: "avatar", "aria-hidden": "true" }, p.name.slice(0, 1).toUpperCase()),
      h("div", {}, h("strong", {}, p.name), h("span", {}, p.id === S.pid ? t("wybrany") : t("kliknij, aby wybrać")))))) : null,
    card(t("Nowy profil"), createForm()));
}

// ---------- Start ----------
const KIND_PL = { voice: t("Rozmowa"), chat: "Quick Chat", lesson: t("Lekcja"), review: t("Powtórki"), placement: t("Poziom"), exam: t("Egzamin"), drill: t("Ćwiczenia"), assessment: t("Diagnoza"), evals: t("Ocena") };
const KIND_GEN = { voice: t("rozmowy"), chat: t("rozmowy"), lesson: t("lekcji"), review: t("powtórek"), placement: t("sprawdzania poziomu"), exam: t("egzaminu"), drill: t("ćwiczeń"), assessment: t("diagnozy") };
// polska odmiana liczebnika: 1 wypowiedź, 2–4 wypowiedzi, 5+ wypowiedzi
const plural = (n, one, few, many) => (I18N.lang === "en" ? `${n} ${n === 1 ? one : many}`
  : `${n} ${n === 1 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many}`);
const KIND_ICON = { voice: "chat", chat: "chat", lesson: "lesson", review: "review", placement: "level", exam: "exam", drill: "weak", assessment: "level", evals: "review" };

async function screenHome(main) {
  if (!S.pid) {
    main.append(h("section", { class: "hero" }, scene(),
      h("div", { class: "hero-inner" }, mascot("idle", 150),
        h("div", { class: "hero-copy" }, h("span", { class: "eyebrow" }, t("Lokalny nauczyciel angielskiego")),
          h("h1", {}, h("span", { class: "sr-only" }, t("Witaj!")), pxText(t("Witaj!"), 6)),
          h("p", {}, t("Rozmowy, lekcje i powtórki działają na tym komputerze. Zacznij od profilu ucznia."))))),
    card(t("Nowy profil"), createForm()));
    return;
  }
  const [d, ac, hs, ls, pr] = await Promise.all([q("/api/home"), q("/api/achievements"), q("/api/history"), q("/api/lessons"), q("/api/progress")]);
  S.catalog = ls.catalog;
  const open = d.open_session;
  const tot = hs.totals;
  const sugName = d.suggested_lesson ? skillPl(d.suggested_lesson.skill_id) : null;

  const hero = h("section", { class: "hero" }, scene(),
    h("div", { class: "hero-inner" }, mascot("idle", 132),
      h("div", { class: "hero-copy" },
        h("span", { class: "eyebrow" }, d.streak > 1 ? t("Seria: {n} dni z rzędu", { n: d.streak }) : t("Twoja wyprawa po angielski")),
        h("h1", {}, h("span", { class: "sr-only" }, t("Cześć, {name}!", { name: d.profile.name })), pxText(t("Cześć, {name}!", { name: d.profile.name }), 5)),
        h("p", {}, open ? t("Masz przerwaną sesję — możesz wrócić dokładnie do tego miejsca.") : t("Od czego zaczynamy?")))));

  const action = (cls, ic, k, title, desc, cta, onclick) => h("button", { type: "button", class: `action ${cls}`, onclick },
    h("span", { class: "k" }, icon(ic, 18), k), h("strong", {}, title), h("span", { class: "d" }, desc), h("span", { class: "go" }, `${cta} →`));
  const actions = h("section", { class: "actions-4", "aria-label": t("Najważniejsze akcje") },
    action("main", "chat", t("1 · Rozmowa"), t("Porozmawiaj z nauczycielem"), t("Swobodna rozmowa po angielsku na wybrany temat."), t("Wybierz temat"), () => go("#/chat")),
    open ? action("", "play", t("2 · Kontynuuj"), t("Wróć do {k}", { k: KIND_GEN[open.kind] || t("sesji") }), t("Postęp przerwanej sesji jest zapisany."), t("Wznów"), () => resume(open))
      : action("", "lesson", t("2 · Nauka"), sugName || t("Lekcja"), d.suggested_lesson?.provisional ? t("Propozycja startowa — możesz wybrać inną misję.") : t("Kolejna misja dobrana do Twoich wyników."), t("Zacznij lekcję"),
        () => startSession("lesson", { text_mode: defaultTextMode() })),
    action("", "review", t("3 · Powtórka"), d.due_reviews ? t("{n} do powtórki", { n: d.due_reviews }) : t("Brak zaległych"), d.due_reviews ? t("Sprawdź, czy pamiętasz — na nowych przykładach.") : t("Wrócą, gdy nadejdzie ich termin."),
      d.due_reviews ? t("Powtórz teraz") : t("Zobacz"), () => (d.due_reviews ? startSession("review", { text_mode: defaultTextMode() }) : go("#/review"))),
    action("", "progress", t("4 · Postępy"), t("{n} lekcji · {t}", { n: tot.lessons_completed, t: fmtMin(tot.study_seconds) }), t("{e} z {n} odznak. Historia z zapisów na tym komputerze.", { e: ac.earned, n: ac.total }), t("Zobacz postępy"), () => go("#/progress")));

  // wyprawa: bieżący rozdział (pierwszy z nieopanowanymi misjami)
  const status = {};
  for (const k of ["mastered", "working", "struggling", "too_few"]) for (const r of pr.skills[k]) status[r.skill] = k;
  const levels = [...new Set(ls.catalog.map((c) => c.cefr))];
  const cur = levels.find((l) => ls.catalog.some((c) => c.cefr === l && status[c.skill_id] !== "mastered")) || levels[0];
  const inCh = ls.catalog.filter((c) => c.cefr === cur);
  const journey = cardT("star", t("Rozdział {n}: {name}", { n: levels.indexOf(cur) + 1, name: CHAPTER[cur] || cur }), h("a", { class: "more", href: "#/lesson" }, t("Mapa misji")),
    h("ul", { class: "mini-list" }, inCh.map((c) => {
      const [label, tone] = STATUS[status[c.skill_id] || "new"];
      return h("li", {}, icon(AREA_ICON[c.area] || "lesson", 22), h("div", {}, h("div", { class: "t" }, skillName(c)), h("div", { class: "s" }, `${cur} · ${areaPl(c.area)}`)), chip(label, tone));
    })));

  const unearned = ac.items.filter((i) => !i.earned && !i.hidden).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  const challenges = cardT("flame", t("Wyzwania"), h("a", { class: "more", href: "#/achievements" }, t("Odznaki")),
    unearned.length ? h("ul", { class: "mini-list" }, unearned.map((i) => h("li", { class: "challenge" }, badgeArt(i.category, tierOf(ac.items, i), false, 36, i.code),
      h("div", {}, h("div", { class: "t" }, achName(i)), h("div", { class: "s" }, `${Math.min(i.progress, i.target)} / ${i.target} · ${achDesc(i)}`), bar(i.progress, i.target, achName(i), "amber")), h("span"))))
      : note(t("Wszystkie wyzwania zdobyte.")));
  const recent = cardT("progress", t("Ostatnio"), h("a", { class: "more", href: "#/progress" }, t("Historia")),
    hs.sessions.length ? h("ul", { class: "mini-list" }, hs.sessions.slice(0, 3).map((s) => h("li", {}, icon(KIND_ICON[s.kind] || "chat", 22),
      h("div", {}, h("div", { class: "t" }, KIND_PL[s.kind] || s.title), h("div", { class: "s" }, `${fmtDate(s.started_at)} · ${fmtMin(s.seconds)}`)),
      h("span", { class: "s" }, s.attempts ? `${s.attempts_correct}/${s.attempts} ${t("zad.")}` : plural(s.user_turns, t("wypowiedź"), t("wypowiedzi"), t("wypowiedzi"))))))
      : note(t("Jeszcze nic — pierwsza rozmowa zajmie 5 minut."), "muted"));

  const pending = d.pending_evals ? h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("review", 30)),
    h("div", {}, h("p", {}, t("ev.pending", { n: d.pending_evals }))), btn(t("ev.run"), () => startSession("evals", {}), "", "play")) : null;
  main.append(hero, pending, actions, h("div", { class: "grid-2" }, journey, h("div", { class: "stack" }, challenges, recent)));
}

function resume(open) {
  const map = { chat: "chat", lesson: "lesson", placement: "placement", review: "review", exam: "exam" };
  if (open.kind === "chat") return startSession("chat", { topic: (open.plan && open.plan.topic && open.plan.topic.id) || "fd.cooking", text_mode: defaultTextMode() });
  if (open.kind === "exam") return go("#/exam");
  if (open.kind === "assessment") return go("#/placement");
  startSession(map[open.kind] || "lesson", { text_mode: defaultTextMode() });
}

function modeRow() {
  const cb = h("input", { type: "checkbox", id: "textmode", checked: defaultTextMode(), disabled: !voiceAvailable() });
  return h("label", { class: "check" }, cb, voiceAvailable() ? t("Tryb tekstowy (bez mikrofonu i głosu)") : t("Tryb tekstowy — głos niedostępny na tym komputerze"));
}
const textMode = () => { const cb = document.getElementById("textmode"); return cb ? cb.checked : defaultTextMode(); };

// ---------- Quick Chat: wybór ----------
const TOPIC_TONE = { food: "amber", tech: "turq", work: "terra", hobbies: "green", travel: "turq", home: "amber", people: "terra", health: "green" };
function topicCard(t, onclick) {
  const tag = t.kind === "roleplay" ? `Roleplay · ${(t.lv || []).join("–")}` : (t.lv ? (t.lv || []).join("–") : t.category_pl);
  return h("button", { class: "topic", type: "button", onclick }, chip(tag, t.kind === "roleplay" ? "terra" : TOPIC_TONE[t.category] || "turq"),
    h("strong", {}, t.pl), t.kind === "roleplay" ? h("em", {}, rpContext(t)) : h("em", { lang: "en" }, t.opener || t.q));
}

const MODE_ABOUT = {
  natural: t("Swobodna rozmowa. Nauczyciel podąża za Tobą i nie poprawia drobiazgów."),
  guided: t("Nauczyciel prowadzi rozmowę, podsuwa zwroty i słownictwo, pomaga budować odpowiedzi."),
  roleplay: t("Nauczyciel gra rolę w konkretnej sytuacji (np. pacjent, rekruter, klient). Uwagi językowe na końcu."),
};
async function screenChat(main) {
  const opt = await q("/api/chat_options");
  const st = { level: opt.prefs.level, category: opt.prefs.category, mode: opt.prefs.mode, seed: null, topics: [] };
  const list = h("div", { class: "topic-grid", "aria-live": "polite" });
  const autoNote = h("p", { class: "note muted" });
  const modeNote = h("p", { class: "note muted" });
  const custom = h("input", { type: "text", maxlength: 80, placeholder: t("np. my first job, Linux servers, a difficult patient…"), "aria-label": t("Własny temat") });
  const minutes = seg(t("Czas rozmowy"), [["", t("bez limitu")], ["5", "5"], ["10", "10"], ["15", "15"], ["20", "20"], ["30", "30"]], "");
  const corr = seg(t("Intensywność poprawek"), [["summary", t("na końcu")], ["periodic", t("czasem")], ["intensive", t("na bieżąco")]], S.settings?.values?.correction || "summary");
  const start = (args) => startSession("chat", { ...args, level: st.level, category: st.category, mode: st.mode,
    minutes: minutes.value || null, correction: corr.value, text_mode: textMode() });
  const customGo = () => (custom.value.trim() ? start({ custom: custom.value.trim() }) : toast(t("Wpisz temat.")));
  custom.addEventListener("keydown", (e) => { if (e.key === "Enter") customGo(); });
  const draw = async () => {
    autoNote.textContent = st.level === "auto" ? opt.auto.notice : t("Ręczny wybór poziomu nie zmienia wyniku diagnozy ani postępów.");
    modeNote.textContent = MODE_ABOUT[st.mode];
    if (st.category === "custom") { list.replaceChildren(note(t("Wpisz własny temat poniżej — rozmowa będzie w wybranym trybie i na wybranym poziomie."), "muted")); st.topics = []; return; }
    st.topics = await q("/api/topics", `&category=${st.category}&level=${st.level}&mode=${st.mode}${st.seed === null ? "" : `&seed=${st.seed}`}`);
    list.replaceChildren(...st.topics.map((t) => topicCard(t, () => start({ topic: t.id }))));
  };
  const cats = h("div", { class: "choice-grid", role: "group", "aria-label": t("Kategoria rozmowy") }, opt.categories.map((c) =>
    h("button", { type: "button", class: "choice", "data-v": c.id, onclick: () => { st.category = c.id; st.seed = null; mark(); draw(); } },
      h("strong", {}, c.pl), h("span", {}, c.about_pl))));
  const mark = () => cats.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === st.category)));
  mark();
  const levels = seg(t("Poziom"), opt.levels.map((l) => [l, l === "auto" ? t("Automatyczny") : l]), st.level, (v) => { st.level = v; draw(); });
  const modes = seg(t("Tryb rozmowy"), opt.modes.map((m) => [m.id, m.pl]), st.mode, (v) => { st.mode = v; st.seed = null; draw(); });
  const go = () => (st.category === "custom" || !st.topics.length ? customGo() : start({ topic: st.topics[0].id }));
  await draw();
  const hist = await q("/api/chats").catch(() => []);
  main.append(
    pageHead(t("Rozmowa z nauczycielem"), "Quick Chat", t("Wybierz poziom, kategorię i tryb. Temat jest opcjonalny — możesz od razu zacząć od propozycji.")),
    h("div", { class: "chat-setup" },
      h("div", { class: "stack" },
        card(null, h("div", { class: "opts" },
          h("div", { class: "opt" }, h("span", {}, t("1 · Poziom")), levels, autoNote),
          h("div", { class: "opt" }, h("span", {}, t("2 · Kategoria")), cats),
          h("div", { class: "opt" }, h("span", {}, t("3 · Tryb")), modes, modeNote)),
          h("div", { class: "row start-row" }, btn(t("Rozpocznij rozmowę"), go, "primary lg", "play"), h("span", { class: "muted" }, t("z pierwszą propozycją poniżej albo z Twoim tematem")))),
        cardT("chat", t("4 · Temat (opcjonalnie)"), h("span", { class: "more" }, btn(t("Wylosuj inne"), () => { st.seed = Math.floor(Math.random() * 1e9); draw(); }, "sm quiet", "dice")),
          list, h("div", { class: "custom-topic" }, custom, btn(t("Rozmawiaj o tym"), customGo, "", "play")))),
      h("div", { class: "stack" },
        h("div", { class: "greet" }, mascot("idle", 72), h("p", { class: "speech", lang: "en" }, "Choose how we talk today. You can change the topic at any time.")),
        card(t("Ustawienia rozmowy"), h("div", { class: "opts" },
          h("div", { class: "opt" }, h("span", {}, t("Czas (minuty)")), minutes),
          h("div", { class: "opt" }, h("span", {}, t("Poprawki")), corr),
          h("div", { class: "opt" }, h("span", {}, t("Tryb")), modeRow()),
          note(t("Quick Chat nie nadaje statusu opanowania. Poprawki to sugestie modelu i mogą być błędne."), "muted"))),
        hist.length ? card(t("Ostatnie rozmowy"), h("ul", { class: "mini-list" }, hist.slice(0, 5).map((c) => h("li", {}, icon("chat", 20),
          h("div", {}, h("div", { class: "t" }, (c.topics || []).join(" → ") || "—"), h("div", { class: "s" }, `${fmtDate(c.started_at)} · ${fmtMin(c.seconds_active)}${c.level ? " · " + c.level : ""}`)),
          h("span", { class: "s" }, t("{n} wyp.", { n: c.user_turns ?? 0 })))))) : null)));
}

// ---------- Lekcje: mapa misji ----------
const CHAPTER = { A1: t("Pierwsze kroki"), A2: t("Codzienne sprawy"), B1: t("Samodzielność"), B2: t("Swoboda"), C1: t("Biegłość"), C2: t("Mistrzostwo") };
const AREA_ICON = { grammar: "lesson", vocabulary: "star", speaking: "mic", writing: "exam", reading: "lesson", listening: "chat" };
const STATUS = {
  mastered: [t("Opanowana"), "amber"], working: [t("W toku"), "green"], struggling: [t("Do poprawy"), "terra"], too_few: [t("Rozpoczęta"), "turq"], new: [t("Nowa"), ""],
};

async function screenLesson(main) {
  const [d, p] = await Promise.all([q("/api/lessons"), q("/api/progress")]);
  S.catalog = d.catalog;
  const status = {};
  for (const k of ["mastered", "working", "struggling", "too_few"]) for (const r of p.skills[k]) status[r.skill] = { k, r };
  const sug = d.suggestion;
  const by = {};
  d.catalog.forEach((c) => (by[c.cefr] = by[c.cefr] || []).push(c));
  main.append(
    pageHead(t("Mapa misji"), t("Lekcje"), t("{n} misji z kompletem materiałów. Każda to krótkie wyjaśnienie, ćwiczenia i rozmowa.", { n: d.catalog.length }), modeRow()),
    sug ? h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("star", 36)),
      h("div", {}, chip(t("Polecana misja"), "amber"), h("h3", {}, skillPl(sug.skill_id)), h("p", {}, sug.reason)),
      btn(t("Zacznij misję"), () => startSession("lesson", { text_mode: textMode() }), "primary lg", "play")) : note(t("Brak lekcji z gotowymi materiałami.")),
    h("div", { class: "legend", "aria-label": t("Legenda statusów") }, Object.values(STATUS).map(([l, c]) => chip(l, c))),
    h("div", { class: "chapters" }, Object.entries(by).map(([cefr, items], i) => h("section", { class: "chapter", "aria-labelledby": `ch-${cefr}` },
      h("div", { class: "chapter-head" }, h("div", { class: "lvl" }, cefr),
        h("div", {}, h("h2", { id: `ch-${cefr}` }, t("Rozdział {n}: {name}", { n: i + 1, name: CHAPTER[cefr] || cefr })),
          h("p", {}, t("{a} z {b} misji rozpoczętych", { a: items.filter((c) => status[c.skill_id]).length, b: items.length })))),
      h("div", { class: "missions" }, items.map((c) => {
        const st = status[c.skill_id];
        const [label, tone] = STATUS[st ? st.k : "new"];
        return h("button", { type: "button", class: `mission${sug && sug.skill_id === c.skill_id ? " suggested" : ""}`, "data-status": st ? st.k : "new",
          onclick: () => startSession("lesson", { skill: c.skill_id, text_mode: textMode() }) },
          h("div", { class: "icon-box" }, icon(st && st.k === "mastered" ? "trophy" : AREA_ICON[c.area] || "lesson", 28)),
          h("strong", {}, skillName(c)),
          h("span", { class: "meta" }, chip(label, tone), h("span", { class: "muted" }, areaPl(c.area))),
          st ? bar(st.r.correct, st.r.attempts, t("Poprawnie {a} z {b}", { a: st.r.correct, b: st.r.attempts })) : null);
      }))))),
    note(t("Materiały nie są jeszcze sprawdzone przez człowieka. Status „Opanowana” nadaje wyłącznie silnik oceny."), "muted"));
}

async function screenReview(main) {
  const [home, p] = await Promise.all([q("/api/home"), q("/api/progress")]);
  await catalog();
  main.append(pageHead(t("Utrwalanie"), t("Powtórki"), t("Krótkie sprawdzenie na nowych przykładach. Termin każdej powtórki wyznacza harmonogram FSRS.")),
    h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("review", 36)),
      h("div", {}, h("h3", {}, home.due_reviews ? t("Do powtórki dziś: {n}", { n: home.due_reviews }) : t("Dziś nie ma zaległych powtórek")),
        h("p", {}, home.due_reviews ? t("Odpowiadaj tak samo jak w lekcji. Niepewnie rozpoznana mowa nie obniża wyniku.") : t("Wrócą, gdy minie ich termin. Możesz w tym czasie zrobić lekcję.")), modeRow()),
      home.due_reviews ? btn(t("Zacznij powtórki"), () => startSession("review", { text_mode: textMode() }), "primary lg", "play") : btn(t("Przejdź do lekcji"), () => go("#/lesson"), "lg")),
    p.due.length ? card(t("Na liście"), h("ul", { class: "mini-list" }, p.due.map((s) => h("li", {}, icon("review", 20), h("div", { class: "t" }, skillPl(s)), h("span"))))) : null,
    note(t("Powtórki nie nadają statusu opanowania. Limit: 20 dziennie."), "muted"));
}

async function screenPlacement(main) {
  const [d, qp] = await Promise.all([q("/api/assessment"), q("/api/placement")]);
  await catalog();
  const p = d.profile;
  const audio = voiceAvailable();
  const picks = new Set(d.areas.filter((a) => (a !== "listening" && a !== "speaking") || audio));
  const boxes = d.areas.map((a) => {
    const need = a === "listening" && !audio ? t("dg.need_audio") : a === "speaking" && !audio ? t("dg.need_mic") : null;
    const cb = h("input", { type: "checkbox", checked: picks.has(a), disabled: !!need, onchange: (e) => (e.target.checked ? picks.add(a) : picks.delete(a)) });
    return h("label", { class: "check" }, cb, h("span", {}, t(`area.${a}`)),
      d.open_areas.includes(a) ? h("em", { class: "muted" }, ` — ${t("dg.not_ready")}`) : null, need ? h("em", { class: "muted" }, ` (${need})`) : null);
  });
  const startFull = () => {
    if (!picks.size) return toast(t("dg.choose_one"));
    startSession("assessment", { areas: d.areas.filter((a) => picks.has(a)), text_mode: textMode() });
  };
  const row = (a) => {
    const lt = a.latest;
    const ev = (a.open_evidence || []).slice(-1)[0];
    const val = lt ? `${lt.label}` : ev ? t("dg.open_ev", { words: ev.words, per: ev.errors_per_100 ?? "—" }) : t("common.not_tested");
    const unc = lt && lt.range ? t("dg.range", { lo: lt.range[0].toFixed(1), hi: lt.range[1].toFixed(1) }) : "—";
    return [t(`area.${a.area}`), val, lt ? t("common.items", { n: a.evidence }) : "—", unc, a.history.length ? a.history.map((x) => `${fmtDay(x.date)}: ${x.level}`).join(" · ") : "—"];
  };
  main.append(pageHead(t("dg.eyebrow"), t("dg.title"), t("dg.sub")),
    d.resume ? h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("level", 36)),
      h("div", {}, h("h3", {}, t("dg.resume", { done: d.resume.finished.length, all: d.resume.areas.length }))),
      btn(t("common.resume"), () => startSession("assessment", { areas: d.resume.areas, text_mode: textMode() }), "primary lg", "play")) : null,
    h("div", { class: "grid-2" },
      card(t("dg.full"), note(t("dg.full_desc")), h("div", { class: "checks" }, boxes),
        h("div", { class: "row" }, modeRow(), btn(t("dg.full_start"), startFull, "primary lg", "level"))),
      card(t("dg.quick"), note(t("dg.quick_desc")),
        h("div", { class: "row" }, btn(t("dg.quick_start"), () => startSession("placement", { text_mode: textMode() }), "", "level")))),
    card(t("dg.profile"), p.areas.some((a) => a.tested) ? table([t("dg.profile"), t("dg.latest"), t("dg.evidence"), t("dg.uncertainty"), t("dg.history")], p.areas.map(row))
      : note(t("dg.none_yet"), "muted"), note(p.notice, "muted")),
    h("div", { class: "grid-2" },
      card(t("dg.recs"), h("ul", { class: "limits" }, p.recommendations.map((r) => h("li", {}, r.text_pl,
        r.skills && r.skills.length ? h("div", { class: "row" }, r.skills.map((sk) => btn(skillPl(sk), () => startSession("lesson", { skill: sk, text_mode: defaultTextMode() }), "sm quiet", "lesson"))) : null)))),
      card(t("dg.bank"), table(["", "A1", "A2", "B1", "B2", "C1"], Object.entries(d.coverage).map(([a, lv]) => [t(`area.${a}`), ...["A1", "A2", "B1", "B2", "C1"].map((l) => lv[l])])),
        p.strengths.length ? note(`${t("dg.strengths")}: ${p.strengths.map((a) => t(`area.${a}`)).join(", ")}`) : null,
        p.weaknesses.length ? note(`${t("dg.weaknesses")}: ${p.weaknesses.map((a) => t(`area.${a}`)).join(", ")}`) : null,
        p.untested.length ? note(`${t("dg.untested")}: ${p.untested.map((a) => t(`area.${a}`)).join(", ")}`, "muted") : null)));
}

// Wykres szacunku (θ) w czasie: pas = ±1 SD; oś Y opisana poziomami A1–C1 (to skala zadań, nie certyfikat).
function thetaChart(points, label) {
  const W = 320, H = 150, P = 28, y = (th) => H - P - ((th - 0.5) / 5.5) * (H - 2 * P), x = (i) => P + (points.length < 2 ? 0 : (i * (W - 2 * P)) / (points.length - 1));
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, at) => { const e = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(at)) e.setAttribute(k, v); return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": label });
  ["A1", "A2", "B1", "B2", "C1"].forEach((lv, k) => {
    svg.append(el("line", { x1: P, x2: W - P, y1: y(k + 1), y2: y(k + 1), class: "grid" }));
    const tx = el("text", { x: 2, y: y(k + 1) + 4, class: "axis" }); tx.textContent = lv; svg.append(tx);
  });
  const band = points.map((p, i) => `${x(i)},${y(p.theta + p.sd)}`).concat(points.map((p, i) => `${x(points.length - 1 - i)},${y(points[points.length - 1 - i].theta - points[points.length - 1 - i].sd)}`));
  svg.append(el("polygon", { points: band.join(" "), class: "band" }));
  svg.append(el("polyline", { points: points.map((p, i) => `${x(i)},${y(p.theta)}`).join(" "), class: "line" }));
  points.forEach((p, i) => { const c = el("circle", { cx: x(i), cy: y(p.theta), r: 3.5, class: "dot" }); const tt = el("title", {}); tt.textContent = `${p.week}: ${p.correct}/${p.n}`; c.append(tt); svg.append(c); });
  return svg;
}

function growthSection(g) {
  const cmpText = (c) => c.status === "insufficient" ? t("gr.insufficient", { n: g.rules.min_trend }) : t(`gr.${c.status}`);
  const closed = ["grammar", "vocabulary", "reading", "listening"].map((a) => {
    const r = g.areas[a];
    return h("article", { class: "growth" }, h("h3", {}, t(`area.${a}`)),
      h("p", { class: `trend ${r.compare.status}` }, cmpText(r.compare)),
      r.timeline.length >= 2 ? thetaChart(r.timeline, `${t("area." + a)} — ${t("gr.chart", { n: g.rules.min_point })}`) : note(t("gr.no_chart"), "muted"),
      h("ul", { class: "limits" }, h("li", {}, t("gr.independent", { n: r.independent })),
        h("li", {}, t("gr.after_hint", { c: r.after_hint.correct, n: r.after_hint.n })), h("li", {}, t("gr.repeats", { n: r.repeats_excluded }))));
  });
  const speech = ["speaking", "writing"].map((a) => {
    const r = g.areas[a];
    return [t(`area.${a}`), r.first.per_100 ?? "—", r.last.per_100 ?? "—", r.compare.status === "insufficient" ? t("common.too_little") : t(`gr.${r.compare.status}`)];
  });
  const rt = g.retention;
  return h("section", { class: "stack" },
    cardT("progress", t("gr.title"), null, note(t("gr.sub")), note(t("gr.compare", { d: g.windows.days }), "muted"),
      h("div", { class: "growth-grid" }, closed)),
    h("div", { class: "grid-2" },
      card(t("gr.speech"), table(["", t("gr.compare", { d: g.windows.days }).split(" vs ")[0], t("gr.compare", { d: g.windows.days }).split(" vs ")[1] || "", ""], speech)),
      card(t("gr.retention"), h("ul", { class: "limits" }, h("li", {}, t("gr.ret_3", { c: rt.after_3_days.correct, n: rt.after_3_days.n })),
        h("li", {}, t("gr.ret_7", { c: rt.after_7_days.correct, n: rt.after_7_days.n })), h("li", {}, t("gr.ret_14", { c: rt.after_14_days.correct, n: rt.after_14_days.n })), h("li", {}, t("gr.ret_rev", { c: rt.reviews.correct, n: rt.reviews.n })),
        h("li", {}, t("gr.errors", { r: g.errors.recurring, s: g.errors.resolved }))))),
    note(t("gr.not_evidence"), "muted"));
}

const REL = {
  "potwierdzony ćwiczeniami": ["ok", t("Potwierdzony ćwiczeniami")],
  "sugestia modelu": ["warn", t("Sugestia modelu")],
  "niepewna transkrypcja STT": ["stt", t("Możliwy błąd rozpoznawania mowy")],
  "za mało danych": ["none", t("Za mało danych")],
};
async function screenWeak(main) {
  const d = await q("/api/weakspots");
  await catalog();
  const head = pageHead(t("Dziennik błędów"), t("Słabe strony"), t("Każdy wpis ma etykietę wiarygodności. „Sugestia modelu” nie jest potwierdzonym błędem."));
  if (!d.has_data) {
    main.append(head, h("div", { class: "empty" }, mascot("idle", 72), h("div", {}, h("p", {}, t("Jeszcze nic tu nie ma. Wpisy pojawią się po rozmowach, lekcjach i powtórkach.")), note(d.stt_uncertain.note, "muted"))));
    return;
  }
  main.append(head,
    h("div", { class: "grid-2" },
      h("div", { class: "stack" },
        d.errors.length ? h("div", { class: "weak-list" }, d.errors.map((e, i) => {
          const [cls, label] = REL[e.reliability] || ["none", e.reliability];
          const tr = e.trend || {};
          return h("article", { class: "weak" },
            h("header", {}, h("strong", {}, `${i + 1}. ${catPl(e.category)}`), h("span", { class: `badge ${cls}` }, label)),
            e.example && cls !== "stt" ? h("p", { class: "example" }, e.correction ? fixLine(e.example, e.correction) : h("span", { lang: "en" }, e.example)) : null,
            h("p", { class: "muted" }, t("{n}× · ostatnio {d} · trend: {t}", { n: e.count, d: fmtDate(e.last_seen), t: tr.direction ? t(tr.direction) : t("za mało danych") })),
            e.skills.length ? h("div", {}, btn(t("Ćwicz to"), () => startSession("drill", { target: String(i + 1), text_mode: defaultTextMode() }), "primary", "play")) : note(t("Brak materiałów do ćwiczeń dla tej kategorii."), "muted"));
        })) : null,
        note(t("Trend pokazujemy dopiero przy co najmniej 5 wypowiedziach w obu okresach (14 dni)."), "muted"),
        d.entries.length ? card(t("ws.entries"), h("div", { class: "weak-list" }, d.entries.map((e) => journalEntry(e)))) : null),
      h("div", { class: "stack" },
        d.weak_skills.length ? card(t("Umiejętności poniżej połowy"), h("ul", { class: "mini-list" }, d.weak_skills.map((w) => h("li", {}, icon("weak", 20),
          h("div", {}, h("div", { class: "t" }, skillPl(w.skill)), h("div", { class: "s" }, `${w.correct}/${w.attempts} poprawnie`)),
          btn(t("Ćwicz"), () => startSession("drill", { target: w.skill, text_mode: defaultTextMode() }), "sm"))))) : null,
        d.vocabulary.length ? card(t("Słowa do utrwalenia"), table([t("Słowo"), t("Pomyłki")], d.vocabulary.map((w) => [w.term, w.misses]))) : null,
        card(t("Niepewne rozpoznanie mowy"), h("p", {}, `${d.stt_uncertain.count} — ${d.stt_uncertain.note}`)),
        d.due_reviews.length ? card(t("Do powtórki"), h("p", {}, d.due_reviews.map(skillPl).join(", ")), btn(t("Zacznij powtórki"), () => go("#/review"))) : null)));
}

function journalEntry(e) {
  const review = async (verdict) => {
    try { await api("/api/weakspots/review", { pid: S.pid, observation_id: e.id, verdict }); route(); } catch (err) { toast(err.message); }
  };
  const [cls] = e.kind === "stt_suspect" ? ["stt"] : e.confidence === "h" ? ["warn"] : ["none"];
  return h("article", { class: `weak${e.counted ? "" : " struck"}` },
    h("header", {}, h("strong", {}, catPl(e.category)), h("span", { class: `badge ${cls}` }, e.reliability)),
    e.utterance ? h("p", {}, h("b", {}, t("ws.said") + ": "), h("span", { lang: "en" }, e.utterance)) : null,
    h("p", { class: "example" }, fixLine(e.span, e.fix)), h("p", {}, e.explanation),
    e.context ? h("p", { class: "muted" }, h("b", {}, t("ws.context") + ": "), h("span", { lang: "en" }, e.context)) : null,
    h("p", { class: "muted" }, `${fmtDate(e.date)} · ${t("ws.source")}: ${e.source}` + (e.review_pl ? ` · ${e.review_pl}` : "") + (e.counted ? "" : ` · ${t("ws.not_counted")}`)),
    h("div", { class: "row" }, e.counted ? [btn(t("ws.dispute"), () => review("disputed"), "sm quiet"), btn(t("ws.stt"), () => review("stt_error"), "sm quiet")]
      : btn(t("ws.restore"), () => review("restored"), "sm quiet"),
    e.counted && e.category ? btn(t("ws.drill"), () => startSession("drill", { target: e.category, text_mode: defaultTextMode() }), "sm", "play") : null));
}

async function screenExam(main) {
  const paths = await q("/api/exams");
  main.append(pageHead(t("Ścieżki egzaminacyjne"), t("Egzaminy"), t("Ćwiczenia w formacie egzaminu. Wynik ćwiczeń nie jest prognozą wyniku egzaminu.")));
  for (const p of paths) {
    const r = p.readiness;
    main.append(cardT("exam", p.name, null,
      note(p.disclaimer, "muted"),
      table([t("Część"), t("Materiały"), t("Wynik ćwiczeń"), t("Stan")], r.sections.map((s) => {
        const cov = p.coverage.find((c) => c.section === s.section) || {};
        return [s.name, cov.status === "ok" ? t("{n} zadań", { n: cov.items }) : (cov.note || "brak"), s.scored ? `${s.correct}/${s.scored}` : "—", s.label];
      })),
      h("ul", { class: "limits" }, [...new Set(r.limits || [])].filter((l) => l !== p.disclaimer).map((l) => h("li", {}, l))),
      p.speaking_topics.length ? h("div", {}, h("h3", { class: "card-title" }, t("Mówienie (w Quick Chat)")), h("div", { class: "row" },
        p.speaking_topics.map((t) => btn(t.pl, () => startSession("chat", { custom: t.q.slice(0, 80), text_mode: defaultTextMode() }), "sm quiet", "chat")))) : null,
      h("div", { class: "row" }, modeRow(), btn(t("Ćwicz tę ścieżkę"), () => startSession("exam", { path: p.id, text_mode: textMode() }), "primary", "play"))));
  }
  main.append(note(t("Matura i Cambridge: przygotowane w architekturze, bez materiałów — nie są jeszcze dostępne."), "muted"));
}

async function screenProgress(main) {
  const [p, hs, ac] = await Promise.all([q("/api/progress"), q("/api/history"), q("/api/achievements")]);
  await catalog();
  const tot = hs.totals;
  const small = (n) => (n < 5 ? t(" (mała próba)") : "");
  const groups = [["mastered", t("Opanowane"), "amber"], ["working", t("W toku"), "green"], ["struggling", t("Wymagają pracy"), "terra"], ["too_few", t("Za mało prób"), "turq"]];
  const status = { ended: t("zakończona"), paused: t("przerwana"), active: t("trwa"), abandoned: t("porzucona") };
  main.append(
    pageHead(t("Dziennik nauki"), t("Postępy"), t("Wszystko pochodzi z bazy na tym komputerze. Czas nauki to przybliżenie z odstępów między zapisami.")),
    growthSection(p.growth),
    h("div", { class: "stats" },
      stat(t("Czas nauki"), fmtMin(tot.study_seconds)), stat(t("Sesje"), tot.sessions), stat(t("Ukończone lekcje"), tot.lessons_completed),
      stat(t("Powtórki"), tot.reviews_done), stat(t("Twoje wypowiedzi"), tot.user_turns), stat(t("Odznaki"), `${ac.earned}/${ac.total}`)),
    h("div", { class: "grid-2" },
      card(t("Umiejętności"), ...groups.map(([k, label, tone]) => p.skills[k].length ? h("div", { class: "stack" },
        h("h3", { class: "card-title" }, chip(label, tone), h("span", { class: "muted" }, String(p.skills[k].length))),
        h("ul", { class: "mini-list" }, p.skills[k].map((r) => h("li", {}, icon("lesson", 20),
          h("div", {}, h("div", { class: "t" }, skillPl(r.skill)), bar(r.correct, r.attempts, `${r.correct} z ${r.attempts}`)),
          h("span", { class: "s" }, `${r.correct}/${r.attempts}${small(r.attempts)}`))))) : null),
        Object.values(p.skills).every((x) => !x.length) ? note(t("Jeszcze nie ma ocenionych zadań."), "muted") : null),
      h("div", { class: "stack" },
        card(t("Poziom (dobrowolne sprawdzenie)"), h("ul", { class: "mini-list" }, p.competence.map((c) => h("li", {}, icon("level", 20),
          h("div", {}, h("div", { class: "t" }, areaPl(c.area)), h("div", { class: "s" }, c.measured_at ? fmtDate(c.measured_at) : "")), h("span", { class: "s" }, c.label || c.state))))),
        p.changes.length ? card(t("Zmiany między sesjami"), h("ul", { class: "mini-list" }, p.changes.map((c) => h("li", {}, icon("progress", 20),
          h("div", { class: "t" }, skillPl(c.skill)), h("span", { class: "s" }, `${c.previous[0]}/${c.previous[1]} → ${c.latest[0]}/${c.latest[1]}${small(c.latest[1])}`))))) : null)),
    card(t("Historia sesji"), hs.sessions.length ? table([t("Data"), t("Rodzaj"), t("Status"), t("Czas"), t("Wypowiedzi"), t("Zadania")],
      hs.sessions.map((s) => [fmtDate(s.started_at), KIND_PL[s.kind] || s.kind, status[s.status] || s.status, fmtMin(s.seconds), s.user_turns, s.attempts ? `${s.attempts_correct}/${s.attempts}` : "—"])) : note(t("Brak sesji."))));
}

// ---------- Osiągnięcia ----------
// Próg w kategorii (rosnąco wg celu) wyznacza kolor ramki odznaki: brąz, srebro, złoto.
function tierOf(items, item) {
  if (item.hidden) return 2;
  const same = items.filter((i) => i.category === item.category && !i.hidden && i.target).sort((a, b) => a.target - b.target);
  return same.length < 2 ? 2 : Math.min(2, Math.floor(same.indexOf(item) * 3 / same.length));
}
const TIER_PL = [t("Brąz"), t("Srebro"), t("Złoto")];
const achName = (i) => (I18N.lang === "en" ? i.name_en : i.name);
const achDesc = (i) => (I18N.lang === "en" ? i.description_en : i.description);

async function screenAchievements(main) {
  const d = await q("/api/achievements");
  const cats = I18N.lang === "en" ? d.categories_en : d.categories;
  if (d.new && d.new.length) toast(t("Nowe osiągnięcie: {x}", { x: d.new.map(achName).join(", ") }));
  const fresh = new Set((d.new || []).map((n) => n.code));
  let filter = "all", query = "", cat = "all";
  const by = {};
  d.items.forEach((i) => (by[i.category] = by[i.category] || []).push(i));
  const shelves = h("div", { class: "stack" });
  const card = (i) => {
    const tier = tierOf(d.items, i);
    const secret = i.hidden && !i.earned;
    return h("article", { class: `badge-card${i.earned ? " earned" : " locked"}${secret ? " secret" : ""}${fresh.has(i.code) ? " fresh" : ""}`,
      "aria-label": `${achName(i)}: ${i.earned ? t("zdobyte") : t("niezdobyte")}` },
      chip(i.hidden ? t("Sekret") : TIER_PL[tier], i.earned ? "amber" : ""),
      i.earned ? null : h("span", { class: "lockmark", "aria-hidden": "true" }, icon("lock", 20)),
      badgeArt(secret ? "secrets" : i.category, tier, i.earned, 80, i.code),
      h("strong", {}, achName(i)), h("span", { class: "desc" }, achDesc(i)),
      i.earned ? h("span", { class: "when" }, t("Zdobyte {d}", { d: fmtDay(i.earned_at) }))
        : secret ? h("span", { class: "when" }, t("Ukryte — odkryjesz je, działając"))
          : h("div", { class: "prog" }, bar(i.progress, i.target, `${achName(i)}: ${i.progress} / ${i.target}`, "amber"), `${i.progress} / ${i.target}`));
  };
  const draw = () => {
    const ql = query.trim().toLowerCase();
    shelves.replaceChildren(...Object.entries(by).filter(([c]) => cat === "all" || c === cat).map(([c, items]) => {
      const shown = items.filter((i) => (filter === "all" || (filter === "earned" ? i.earned : filter === "secret" ? i.hidden : !i.earned))
        && (!ql || `${achName(i)} ${achDesc(i)}`.toLowerCase().includes(ql)));
      if (!shown.length) return null;
      return h("section", { class: "shelf", "aria-labelledby": `cat-${c}` },
        h("div", { class: "shelf-head" }, badgeArt(c, 2, items.some((i) => i.earned), 28, c), h("h2", { id: `cat-${c}` }, cats[c] || c),
          h("span", { class: "count" }, `${items.filter((i) => i.earned).length}/${items.length}`)),
        h("div", { class: "badges" }, shown.map(card)));
    }).filter(Boolean));
    if (!shelves.children.length) shelves.append(note(t("Nic nie pasuje do filtrów."), "muted"));
  };
  const near = d.items.filter((i) => !i.earned && !i.hidden && i.progress > 0).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  const search = h("input", { type: "search", placeholder: t("Szukaj odznaki…"), "aria-label": t("Szukaj odznaki…"), oninput: (e) => { query = e.target.value; draw(); } });
  const catSel = h("select", { "aria-label": t("Kategoria"), onchange: (e) => { cat = e.target.value; draw(); } },
    h("option", { value: "all" }, t("Wszystkie kategorie")), Object.keys(by).map((c) => h("option", { value: c }, cats[c] || c)));
  main.append(
    h("section", { class: "trophy-hero" }, icon("trophy", 84),
      h("div", {}, h("span", { class: "eyebrow" }, t("Sala trofeów")),
        h("h1", {}, h("span", { class: "sr-only" }, t("Osiągnięcia")), pxText(t("Osiągnięcia"), 5)),
        h("p", {}, t("Odznaki nagradzają regularną pracę. Nie oznaczają opanowania języka.")),
        bar(d.earned, d.total, t("Zdobyte {a} z {b}", { a: d.earned, b: d.total }), "amber")),
      h("div", { class: "counter" }, h("strong", {}, `${d.earned}/${d.total}`),
        h("span", {}, t("standardowe {a}/{b} · sekrety {c}/{e}", { a: d.standard.earned, b: d.standard.total, c: d.secret.earned, e: d.secret.total })))),
    near.length ? cardT("flame", t("Najbliżej zdobycia"), null,
      h("div", { class: "near" }, near.map((i) => h("div", { class: "badge-row" }, badgeArt(i.category, tierOf(d.items, i), false, 48, i.code),
        h("div", {}, h("strong", {}, achName(i)), h("div", { class: "muted" }, achDesc(i)), bar(i.progress, i.target, achName(i), "amber")))))) : null,
    h("div", { class: "row filters" }, seg(t("Filtr odznak"), [["all", t("Wszystkie")], ["earned", t("Zdobyte")], ["locked", t("Do zdobycia")], ["secret", t("Sekrety")]], filter, (v) => { filter = v; draw(); }),
      catSel, search),
    shelves);
  draw();
}

// ---------- Ustawienia ----------
const SET_LABELS = {
  chat_model: t("Model rozmowy"), tts_voice: t("Głos nauczyciela"), speed: t("Tempo mowy"), correction: t("Poprawki w rozmowie"),
  session_minutes: t("Dzienny czas nauki (min)"), io_mode: t("Tryb domyślny"), mic_mode: t("Mikrofon"),
  input_device: t("Mikrofon (urządzenie)"), output_device: t("Głośnik (urządzenie)"), stt_model: t("Rozpoznawanie mowy"),
  allow_unreviewed: t("Używaj materiałów niesprawdzonych przez człowieka"), conversation_mode: t("Domyślna aktywność"), target_lang: t("Język nauki"),
  stt_confirm: t("Potwierdzanie rozpoznanej mowy"), ui_lang: t("Język interfejsu"), mascot: t("Maskotka (propozycja)"),
};
const SET_GROUPS = [[t("Rozmowa i nauka"), ["ui_lang", "mascot", "chat_model", "correction", "conversation_mode", "session_minutes", "allow_unreviewed", "target_lang"]],
  [t("Głos i dźwięk"), ["io_mode", "tts_voice", "speed", "stt_confirm", "mic_mode", "input_device", "output_device"]]];
const SPEED_LABELS = { slow: t("wolno"), normal: t("normalnie"), fast: t("szybko") };
const CHOICE_LABELS = { A: t("A — Obwód"), B: t("B — Słuchawki"), C: t("C — Bit"), classic: t("dotychczasowa żaba"), pl: t("polski"), summary: t("swobodna — uwagi głównie na końcu"), periodic: t("zrównoważona — krótkie korekty w trakcie"), intensive: t("intensywna — częste korekty i ćwiczenie"),
  uncertain: t("tylko gdy niepewne"), always: t("zawsze"), never: t("nigdy"), ptt: t("kliknij, aby mówić"), auto: t("automatyczny"), voice: t("głosowy"), text: t("tekstowy"), quick_chat: "Quick Chat", lesson: t("lekcja"), en: t("angielski") };
// F7: reset postępów i usunięcie profilu — potwierdzenie nazwą profilu, domyślnie kopia zapasowa.
function dangerZone() {
  const who = S.profiles.find((p) => p.id === S.pid);
  if (!who) return null;
  const confirm = h("input", { type: "text", maxlength: 40, "aria-label": t("Wpisz nazwę profilu, aby potwierdzić"), placeholder: who.name });
  const bk = h("input", { type: "checkbox", checked: true });
  const run = async (op) => {
    const msg = op === "delete" ? t("Usunąć profil {name} i wszystkie jego dane?", { name: who.name })
      : t("Usunąć całą historię nauki profilu {name}? Ustawienia zostaną.", { name: who.name });
    if (!window.confirm(msg)) return;
    try {
      const r = await api(`/api/profiles/${op}`, { pid: S.pid, confirm: confirm.value, backup: bk.checked });
      toast((op === "delete" ? t("Profil usunięty.") : t("Postępy zresetowane.")) + (r.backup ? " " + t("Kopia: {p}", { p: r.backup }) : ""));
      if (op === "delete") { await loadProfiles(); S.settings = null; go("#/profiles"); route(); } else { S.settings = null; go("#/home"); }
    } catch (e) { toast(e.message); }
  };
  return h("section", { class: "card danger" }, h("h2", { class: "card-title" }, t("Profil — operacje nieodwracalne")),
    h("p", {}, t("Reset postępów usuwa historię nauki, wyniki, dziennik i osiągnięcia, ale zostawia profil i ustawienia. Usunięcie profilu usuwa wszystko. Inne profile nie są zmieniane.")),
    h("label", { class: "field" }, h("span", {}, t("Wpisz nazwę profilu, aby potwierdzić")), confirm),
    h("label", { class: "check" }, bk, t("Najpierw zapisz kopię zapasową (JSON)")),
    h("div", { class: "row" }, btn(t("Resetuj postępy"), () => run("reset"), "danger"), btn(t("Usuń profil"), () => run("delete"), "danger")));
}

async function screenSettings(main) {
  const d = S.settings = await q("/api/settings");
  const st = S.system;
  const fields = {};
  const field = (key) => {
    const spec = d.schema[key];
    if (!spec) return null;
    const val = d.values[key];
    let input;
    if (key === "tts_voice" && st && st.voices.length) input = h("select", {}, st.voices.map((v) => h("option", { value: v, selected: v === val }, v)));
    else if (key === "input_device" || key === "output_device") {
      if (!st || st.audio_error) return null;
      input = h("select", {}, h("option", { value: "default", selected: val === "default" }, t("systemowe")), st.devices.map((v) => h("option", { value: v, selected: v === val }, v)));
    } else if (spec.type === "choice") input = h("select", {}, spec.choices.map((c) => h("option", { value: c, selected: String(c) === String(val) },
      key === "chat_model" ? `${c}${st && st.models.includes(c) ? "" : t(" (nie pobrany)")}` : (CHOICE_LABELS[c] || c))));
    else if (key === "speed" && spec.presets) {
      const named = Object.entries(spec.presets);
      const custom = !named.some(([, v]) => Number(v) === Number(val));
      input = h("select", {}, named.map(([n, v]) => h("option", { value: n, selected: Number(v) === Number(val) }, `${SPEED_LABELS[n] || n} (${v})`)),
        custom ? h("option", { value: val, selected: true }, t("własne ({v})", { v: val })) : null);
    }
    else if (spec.type === "float") input = h("input", { type: "number", min: spec.min, max: spec.max, step: 0.05, value: val });
    else if (spec.type === "bool") input = h("input", { type: "checkbox", checked: !!val });
    else return null;
    fields[key] = input;
    return h("label", { class: "field" }, h("span", {}, SET_LABELS[key] || key), input);
  };
  const save = async () => {
    const changes = {};
    for (const [k, el] of Object.entries(fields)) changes[k] = el.type === "checkbox" ? el.checked : el.value;
    try {
      S.settings.values = await api("/api/settings", { pid: S.pid, changes });
      if (setLang(S.settings.values.ui_lang)) return;          // inny język interfejsu: przeładowanie
      window.MASCOT_KEY = S.settings.values.mascot;
      document.getElementById("brand").replaceChildren(mascotHead(36), h("span", {}, pxText("AI Tutor", 3), h("small", {}, t("angielski · lokalnie"))));
      toast(t("Zapisano ustawienia.")); setStatus();
    }
    catch (e) { toast(e.message); }
  };
  main.append(pageHead(t("Profil ucznia"), t("Ustawienia"), t("Zmiany dotyczą tylko wybranego profilu.")),
    ...SET_GROUPS.map(([title, keys]) => card(title, h("form", { class: "settings", onsubmit: (e) => e.preventDefault() }, keys.map(field)))),
    h("div", { class: "row" }, btn(t("Zapisz ustawienia"), save, "primary lg", "check")),
    note(t("Model oceny zostaje bez zmian (Qwen3 8B): jego zmiana wymaga kontroli jakości. Model rozmowy musi być pobrany w Ollamie."), "muted"),
    dangerZone(),
    card(t("Ten komputer"), table([t("Element"), t("Stan")], st ? [
      ["Ollama", st.ollama ? t("działa") : t("nie odpowiada — uruchom `ollama serve`")], [t("Pobrane modele"), st.models.join(", ") || "—"],
      [t("Model oceny"), st.roles.evaluation || "—"], [t("Głos (Kokoro)"), st.kokoro ? t("gotowy, {n} głosów", { n: st.voices.length }) : t("brak plików modelu")],
      ["Audio", st.audio_error ? t("niedostępne: {e}", { e: st.audio_error }) : st.devices.join("; ")]] : [])));
}

// ---------- sesja ----------
const KIND_TITLE = { chat: "Quick Chat", lesson: t("Lekcja"), placement: t("Szybkie dopasowanie"), review: t("Powtórki"), drill: t("Ćwiczenia słabej strony"), exam: t("Ćwiczenia egzaminacyjne"), assessment: t("Diagnoza"), evals: t("Dokończenie oceny") };
const STATE_PL = { listening: t("Słucham…"), thinking: t("Myślę…"), speaking: t("Mówię…"), turn: t("Twoja kolej"), idle: t("Sesja zakończona"), connecting: t("Łączę…"),
  encouraging: t("Spróbuj jeszcze raz"), success: t("Dobrze!"), explaining: t("Wyjaśniam"), error: t("Problem") };

function newSession(kind, text) {
  return { kind, phase: null, running: true, text, log: [], task: null, heard: null, feedback: null, hint: null, goal: null, goalText: null,
    recording: false, waiting: true, speaking: false, topic: null, said: null, verdictAt: 0, error: null, started: Date.now(), layout: null, lastKind: null };
}

async function startSession(kind, args) {
  try {
    await api("/api/session/start", { pid: S.pid, kind, args });
    S.seq = 0;
    S.session = newSession(kind, !!args.text_mode);
    go("#/session");
  } catch (e) { toast(e.message); }
}

function verdictOf(s) {
  if (s.hint) return "hint";
  if (!s.feedback) return null;
  return s.feedback.startsWith("✓") ? "ok" : /^(✗|Poprawna odpowiedź)/.test(s.feedback) ? "no" : null;
}
function mascotState(s) {
  if (s.error && !s.running) return "error";
  if (!s.running) return s.log.length ? "idle" : "connecting";
  if (s.recording) return "listening";
  if (s.waiting) return s.log.length ? "thinking" : "connecting";
  if (s.speaking && !s.text) return "speaking";
  const v = verdictOf(s);
  if (v === "ok" && Date.now() - s.verdictAt < 4000) return "success";
  if (v === "no" || v === "hint") return "encouraging";
  if (s.kind !== "chat" && s.phase !== "chat" && !s.task && s.goalText) return "explaining";
  return "turn";
}
const FROG_STATE = { error: "thinking", connecting: "idle", turn: "idle" };
function nextText(s, state) {
  const task = s.kind !== "chat" && s.phase !== "chat";
  const hasOpts = task && s.task && /^\s+\d+\.\s+/m.test(s.task.text);
  return {
    connecting: t("Uruchamiam nauczyciela…"),
    listening: t("Mów teraz. Kliknij Stop, gdy skończysz."),
    thinking: task ? t("Sprawdzam odpowiedź…") : t("Układam odpowiedź…"),
    speaking: t("Nauczyciel mówi. Kliknij mikrofon, aby przerwać i odpowiedzieć."),
    success: t("Dobrze! Za chwilę kolejny krok."),
    encouraging: t("Prawie. Spróbuj jeszcze raz — wskazówka poniżej."),
    explaining: t("Przeczytaj krótkie wyjaśnienie. Pierwsze zadanie zaraz się pojawi."),
    idle: t("Sesja zakończona. Wyniki są zapisane."),
    error: s.error || t("Coś poszło nie tak."),
    turn: task ? (hasOpts ? t("Wybierz odpowiedź albo powiedz ją.") : (s.text ? t("Napisz odpowiedź na zadanie.") : t("Odpowiedz: kliknij mikrofon albo napisz.")))
      : (s.text ? t("Twoja kolej: napisz odpowiedź.") : t("Twoja kolej: kliknij Mów i odpowiedz.")),
  }[state];
}

// Wyjaśnienie z pakietu treści: bez instrukcji CLI i bez technicznych identyfikatorów kategorii.
function lessonText(text) {
  return text.split("\n").filter((l) => !/^(Ćwiczenia:|Dlaczego ten cel: Cel wskazany ręcznie)/.test(l.trim()))
    .map((l) => l.replace(/\s*\[([a-z_]+(?:\.[a-z_0-9]+)?)\]/g, "").replace(/`([a-z_]+(?:\.[a-z_0-9]+)?)`/g, (m, c) => (CAT_PL[c] ? `**${CAT_PL[c]}**` : m)))
    .join("\n");
}

function chatLayout(s) { return s.kind === "chat" || s.phase === "chat"; }

function screenSession(main) {
  const s = S.session;
  if (!s) { main.append(h("div", { class: "empty" }, mascot("idle", 72), h("div", {}, h("p", {}, t("Brak aktywnej sesji.")), btn(t("Na start"), () => go("#/home"), "primary")))); return; }
  s.layout = chatLayout(s) ? "chat" : "task";
  const send = async (text) => {
    try { await api("/api/session/send", { text }); if (text) { s.waiting = true; s.hint = null; drawSide(); } } catch (e) { toast(e.message); }
  };
  const input = h("input", { type: "text", id: "say", maxlength: 500, lang: "en", placeholder: s.text ? t("Napisz po angielsku…") : t("Albo napisz po angielsku…"), "aria-label": t("Twoja odpowiedź") });
  const submit = () => {
    const t = input.value.trim(); if (!t) return; input.value = "";
    if (s.layout === "task") { drawEvent({ kind: "you", text: t, seq: -1 }, true); s.answered = t; }   // silnik nie powtarza odpowiedzi
    send(t);
  };
  S.answer = (t) => { input.value = t; submit(); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const composer = h("div", { class: "composer" }, input, btn(t("Wyślij"), submit, "primary"));
  const mic = () => (s.text ? null : h("button", { type: "button", class: "mic-big", id: "micbtn", "aria-label": t("Mów"), onclick: () => send("") }, icon("mic", 34), h("span", { class: "mic-label" }, t("Mów"))));
  const stop = btn(s.kind === "chat" ? t("Zakończ rozmowę") : t("Przerwij i zapisz"), () => api("/api/session/stop", {}).catch((e) => toast(e.message)), "danger block end");
  const log = S.logEl = h("div", { class: "log", id: "log", "aria-live": "polite", "aria-label": t("Przebieg rozmowy") });

  if (s.layout === "chat") {
    const tools = s.kind === "chat"
      ? [[t("Powtórz"), "Could you repeat that, please?"], [t("Wyjaśnij prościej"), "Could you explain that in simpler words?"], [t("Zmień temat"), "Can we change the topic?", "wide"]]
      : [[t("Powtórz"), "Could you repeat that, please?"], [t("Wyjaśnij prościej"), "Could you explain that in simpler words?"]];
    main.append(h("div", { class: "session chat" },
      h("aside", { class: "stage", id: "stage", "aria-label": t("Nauczyciel") },
        mascot("idle", 150), h("span", { class: "state-label", id: "sstate", "data-state": "connecting", role: "status" }, STATE_PL.connecting),
        h("p", { class: "next", id: "next" }), mic(),
        h("div", { class: "topic-now", id: "topicnow" }),
        h("div", { class: "tools" }, tools.map(([l, t, c]) => btn(l, () => send(t), `sm ${c || ""}`))), stop),
      h("section", { class: "convo", "aria-label": t("Rozmowa") },
        h("div", { class: "convo-head" }, h("h1", {}, s.kind === "chat" ? "Quick Chat" : t("Rozmowa po lekcji")), h("span", { class: "muted" }, s.text ? t("tryb tekstowy") : t("tryb głosowy"))),
        log,
        s.text ? composer : h("details", { class: "write-toggle" }, h("summary", {}, t("Wolę napisać")), composer))));
  } else {
    const tools = ["exam", "placement"].includes(s.kind) ? [[t("Nie wiem"), "I don't know"], [t("Pomiń"), "Can we skip this?"]]
      : [[t("Podpowiedź"), "Could you explain, please?"], [t("Nie wiem"), "I don't know"], [t("Pomiń"), "Can we skip this?", "wide"]];
    main.append(h("div", { class: "session task" },
      h("div", { class: "task-main" },
        h("header", { class: "mission-bar" }, icon(KIND_ICON[s.kind] || "lesson", 36),
          h("div", {}, h("h1", {}, KIND_TITLE[s.kind] || s.kind), h("div", { class: "goal-line", id: "goalline" }), h("div", { id: "steps" }))),
        h("div", { class: "now", id: "now", role: "status" }),
        h("section", { class: "task-card", id: "taskcard", "aria-live": "polite" }),
        h("div", { class: "answer", id: "answer" }, mic(), h("div", { class: "composer paper" }, input, btn(t("Wyślij"), submit, "primary"))),
        h("div", { id: "verdict", "aria-live": "polite" }),
        h("details", { class: "transcript" }, h("summary", {}, t("Przebieg sesji")), log)),
      h("aside", { class: "coach", id: "stage", "aria-label": t("Nauczyciel") },
        h("div", { class: "stage" }, mascot("idle", 130), h("span", { class: "state-label", id: "sstate", "data-state": "connecting" }, STATE_PL.connecting),
          h("div", { class: "said", id: "said", hidden: true })),
        h("div", { class: "tools" }, tools.map(([l, t, c]) => btn(l, () => send(t), `sm ${c || ""}`))),
        stop, h("div", { id: "explainbox" }))));
  }
  s.log.forEach((ev) => drawEvent(ev, false));
  drawSide();
  if (s.text || s.layout === "task") input.focus();
  pollSession();
}

function drawEvent(ev, store = true) {
  const s = S.session;
  const k = ev.kind;
  if (store) {
    s.log.push(ev);
    if (k === "task") { s.task = ev; s.heard = null; s.feedback = null; s.hint = null; s.answered = null; }
    if (k === "heard") s.heard = ev.text;
    if (k === "feedback") { s.feedback = ev.text; s.hint = null; s.verdictAt = Date.now(); }
    if (k === "hint") s.hint = ev.text;
    if (k === "goal") { s.goalText = ev.text; s.goal = ev.text.split("\n")[0].replace(/^Cel lekcji:\s*\S+\s*\((\w+)\)\s*—\s*/, "$1 · "); }
    if (k === "recording") { s.recording = true; s.speaking = false; }
    if (k === "info" && ev.text.trim().startsWith(t("Teraz krótka rozmowa"))) s.phase = "chat";
    if (["you", "tutor", "prompt", "end", "heard"].includes(k)) s.recording = false;
    if (["you", "heard"].includes(k)) s.waiting = true;
    if (["tutor", "task", "feedback", "hint", "prompt", "error", "end", "goal", "correction_head"].includes(k)) s.waiting = false;
    if (k === "tutor") { s.speaking = true; s.said = (s.lastKind === "tutor" && s.said ? `${s.said} ` : "") + ev.text; }
    if (["prompt", "listening", "end", "you"].includes(k)) s.speaking = false;
    if (k === "error") s.error = ev.text;
    if (k === "chatinfo") s.chatinfo = ev.text;
    if (k === "scenario") s.scenario = ev.text;
    if (k === "info" && ev.text.startsWith("Quick Chat — temat:")) s.topic = ev.text.replace("Quick Chat — temat:", "").split("(")[0].trim().replace(/\.$/, "");
    if (k === "notice" && /^(nowy temat|new topic):/.test(ev.text)) s.topic = ev.text.replace(/^(nowy temat|new topic):/, "").trim();
    if (!["prompt", "metric", "listening"].includes(k)) s.lastKind = k;
  }
  const log = S.logEl;            // także przed wstawieniem widoku do strony (odtwarzanie historii po zmianie układu)
  if (!log) return;
  if (["prompt", "start", "metric", "listening", "recording", "chatinfo"].includes(k)) return;
  if (k === "info" && /^(\[Enter\]|Profil:|Quick Chat — temat:)/.test(ev.text)) return;        // diagnostyka i instrukcje CLI
  if (k === "goal" && s.layout === "task") return;                                              // cel ma własne miejsce
  const last = log.lastElementChild;
  if (k === "tutor" && last && last.classList.contains("tutor") && last.dataset.seq == ev.seq - 1) {   // jedna wypowiedź, kilka zdań
    last.querySelector(".bubble").textContent += " " + ev.text; last.dataset.seq = ev.seq; log.scrollTop = log.scrollHeight; return;
  }
  let el;
  if (k === "tutor") el = h("div", { class: "msg tutor" }, h("div", { class: "avatar-s", "aria-hidden": "true" }, mascotHead(30)), h("div", {}, h("b", {}, MASCOT_NAME), h("p", { class: "bubble", lang: "en" }, ev.text)));
  else if (k === "you") el = h("div", { class: "msg you" }, h("b", {}, t("Ty")), h("p", { lang: "en" }, ev.text));
  else if (k === "task") el = h("div", { class: "msg task" }, h("b", {}, t("Zadanie {a}/{b}", { a: ev.index, b: ev.total })), h("pre", { lang: "en" }, ev.text));
  else if (k === "goal") el = h("div", { class: "msg goal" }, h("b", {}, t("Cel")), rich(ev.text));
  else if (k === "feedback") el = h("div", { class: `msg feedback${ev.text.startsWith("✓") ? " ok" : /^(✗|Poprawna)/.test(ev.text) ? " no" : ""}` }, h("pre", {}, ev.text.trim()));
  else if (k === "hint") el = h("div", { class: "msg hint" }, h("b", {}, t("Wskazówka")), h("p", {}, ev.text));
  else if (k === "correction_head") el = h("div", { class: "msg correction-head" }, t("Do poprawy w tej rozmowie (sugestie modelu)"));
  else if (k === "correction") el = h("div", { class: "msg correction" }, h("div", { class: "fix" }, fixLine(ev.span, ev.fix)),
    ev.why ? h("div", { class: "why" }, ev.why) : null, ev.stt ? h("div", { class: "why" }, t("Możliwe, że źle usłyszałem — sprawdź, czy tak powiedziałeś/aś.")) : null);
  else if (k === "scenario") el = h("div", { class: "msg scenario" }, h("b", {}, t("Scenariusz")), h("p", {}, ev.text));
  else if (k === "heard") el = h("div", { class: "msg heard" }, `Rozpoznano: ${ev.text}`);
  else if (k === "stt_confirm") el = sttConfirm(ev);
  else if (k === "error") el = h("div", { class: "msg error", role: "alert" }, h("b", {}, t("Problem")), h("p", {}, ev.text));
  else if (k === "end") el = h("div", { class: "msg sys" }, ev.code ? t("Sesja zakończona z błędem.") : t("Sesja zamknięta. Wyniki zapisano."));
  else el = h("div", { class: `msg ${k}` }, h("pre", {}, ev.text.trim()));
  el.dataset.seq = ev.seq;
  log.append(el);
  log.scrollTop = log.scrollHeight;
}

// F7: niepewne rozpoznanie mowy wraca do ucznia przed oceną. Poprawka to korekta ROZPOZNANIA, nie błąd językowy.
function sttConfirm(ev) {
  const field = h("input", { type: "text", value: ev.text, maxlength: 500, lang: "en", "aria-label": t("Rozpoznany tekst — możesz go poprawić") });
  let done = false;
  const box = h("div", { class: "msg stt-confirm", role: "group", "aria-label": t("Sprawdź rozpoznanie") });
  const reply = async (text) => {
    if (done) return; done = true;
    box.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
    try { await api("/api/session/send", { text }); } catch (e) { toast(e.message); done = false; }
  };
  const sendIt = () => { const t = field.value.trim(); reply(t === ev.text ? "" : t); };
  field.addEventListener("keydown", (e) => { if (e.key === "Enter") sendIt(); });
  box.append(h("b", {}, t("Czy dobrze usłyszałem?")),
    ev.unsure ? h("p", { class: "muted" }, t("Niepewne słowa: {w}", { w: ev.unsure })) : null, field,
    h("p", { class: "muted" }, t("Popraw tekst, jeśli rozpoznanie jest błędne — to nie jest liczone jako błąd językowy.")),
    h("div", { class: "row" }, btn(t("Wyślij"), sendIt, "primary"), btn(t("Nagraj ponownie"), () => reply("r"))));
  setTimeout(() => field.focus(), 0);
  return box;
}

function drawSide() {
  const s = S.session;
  if (!document.getElementById("stage")) return;
  if (chatLayout(s) !== (s.layout === "chat")) { route(); return; }          // lekcja przeszła w rozmowę
  document.querySelectorAll(".composer input, .composer button, .tools button, #micbtn").forEach((b) => { b.disabled = !s.running; });
  const state = mascotState(s);
  document.querySelectorAll("#stage .mascot").forEach((m) => { m.dataset.state = FROG_STATE[state] || state; });
  const st = document.getElementById("sstate");
  st.dataset.state = state; st.textContent = STATE_PL[state];
  const mic = document.getElementById("micbtn");
  if (mic) { mic.classList.toggle("on", s.recording); mic.setAttribute("aria-label", s.recording ? t("Stop — zakończ nagrywanie") : t("Mów")); mic.querySelector(".mic-label").textContent = s.recording ? "Stop" : t("Mów"); }
  const end = document.querySelector(".end");
  if (end && end.tagName === "BUTTON" && !s.running) end.replaceWith(h("div", { class: "row end" }, btn(t("Zobacz postępy"), () => go("#/progress"), "primary"), btn(t("Na start"), () => go("#/home"))));
  if (s.layout === "chat") {
    document.getElementById("next").textContent = nextText(s, state);
    const min = Math.floor((Date.now() - s.started) / 60000);
    document.getElementById("topicnow").replaceChildren(h("span", {}, s.kind === "chat" ? t("Temat") : t("Rozmowa po lekcji")),
      h("strong", {}, s.kind === "chat" ? (s.topic || "…") : (s.goal || "…")),
      h("div", { class: "muted" }, [s.chatinfo, `${min} min`].filter(Boolean).join(" · ")));
    return;
  }
  const now = document.getElementById("now");
  now.dataset.state = state; now.textContent = nextText(s, state);
  document.getElementById("goalline").textContent = s.goal || "";
  if (s.task) document.getElementById("steps").replaceChildren(h("div", { class: "steps", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": s.task.total, "aria-valuenow": s.task.index - 1, "aria-label": t("Zadanie {a} z {b}", { a: s.task.index, b: s.task.total }) },
    Array.from({ length: s.task.total }, (_, i) => h("i", { class: i < s.task.index - 1 ? "done" : i === s.task.index - 1 ? "now" : "" }))));
  const said = document.getElementById("said");
  if (s.said) { said.hidden = false; said.replaceChildren(h("b", {}, t("Nauczyciel mówi")), h("span", { lang: "en" }, s.said)); }
  const ex = document.getElementById("explainbox");
  const body = s.goalText ? s.goalText.split("\n").slice(1).join("\n").trim() : "";
  if (body && !ex.firstChild) ex.append(h("details", { class: "explain", open: true }, h("summary", {}, t("Wyjaśnienie")), rich(lessonText(body))));
  const card = document.getElementById("taskcard");
  const key = s.task ? String(s.task.seq) : "none";
  if (card.dataset.key !== key) {
    card.dataset.key = key;
    if (s.task) {
      const opts = [...s.task.text.matchAll(/^\s+\d+\.\s+(.+)$/gm)].map((m) => m[1].trim());
      const stem = s.task.text.replace(/\n\s+\d+\.\s+.+/g, "");
      card.replaceChildren(...[h("span", { class: "k" }, t("Zadanie {a} z {b}", { a: s.task.index, b: s.task.total })), h("pre", { class: "stem", lang: "en" }, stem),
        opts.length ? h("div", { class: "options" }, opts.map((o, i) => h("button", { type: "button", class: "btn", onclick: () => S.answer(o) }, h("span", { class: "n" }, String(i + 1)), o))) : null].filter(Boolean));
    } else card.replaceChildren(h("span", { class: "k" }, t("Za chwilę")), h("p", { class: "stem" }, t("Pierwsze zadanie pojawi się za moment.")));
  }
  card.querySelectorAll(".options button").forEach((b) => { b.disabled = !s.running; });
  const v = verdictOf(s);
  document.getElementById("verdict").replaceChildren(...[
    s.heard ? h("div", { class: "verdict" }, h("b", {}, t("Rozpoznano")), h("span", { lang: "en" }, s.heard))
      : s.answered && (s.feedback || s.hint) ? h("div", { class: "verdict" }, h("b", {}, t("Twoja odpowiedź")), h("span", { lang: "en" }, s.answered)) : null,
    v === "ok" ? h("div", { class: "verdict ok" }, h("b", {}, t("Dobrze")), s.feedback) : null,
    v === "no" ? h("div", { class: "verdict no" }, h("b", {}, t("Jeszcze nie")), s.feedback) : null,
    v === "hint" ? h("div", { class: "verdict hint" }, h("b", {}, t("Wskazówka")), s.hint) : null,
    v === null && s.feedback ? h("div", { class: "verdict" }, s.feedback) : null,
  ].filter(Boolean));
}

async function pollSession() {
  clearTimeout(S.poll);
  if (!S.session || location.hash !== "#/session") return;
  try {
    const r = await api(`/api/session/events?since=${S.seq}`);
    for (const ev of r.events) { S.seq = ev.seq; drawEvent(ev); }
    S.session.running = r.running;
    drawSide();
    if (!r.running) { renderNav("session"); return; }
  } catch (e) { toast(e.message); }
  S.poll = setTimeout(pollSession, 350);
}

// ---------- routing ----------
const ROUTES = { home: screenHome, chat: screenChat, lesson: screenLesson, review: screenReview, placement: screenPlacement, weak: screenWeak, exam: screenExam, progress: screenProgress, achievements: screenAchievements, settings: screenSettings, session: screenSession, profiles: screenProfiles };
async function route() {
  const id = (location.hash.replace(/^#\//, "") || "home").split("?")[0];
  const fn = ROUTES[id] || screenHome;
  const main = document.getElementById("main");
  renderNav(id);
  main.replaceChildren(h("p", { class: "loading" }, t("Wczytuję…")));
  if (!S.pid && !["home", "profiles"].includes(id)) { go("#/home"); return; }
  const frag = h("div", { class: "screen" });
  const append = frag.append.bind(frag);
  frag.append = (...kids) => append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  try {
    if (S.pid && !S.settings) S.settings = await q("/api/settings").catch(() => null);
    if (S.settings && setLang(S.settings.values.ui_lang)) return;   // profil z innym językiem interfejsu
    if (S.settings) window.MASCOT_KEY = S.settings.values.mascot;
    await fn(frag);
  } catch (e) {
    frag.replaceChildren(h("div", { class: "empty" }, mascot("thinking", 72), h("div", {}, h("p", {}, e.message), btn(t("Spróbuj ponownie"), route, "primary"))));
  }
  main.replaceChildren(frag);
  setStatus();
}

async function boot() {
  document.querySelector(".skip").textContent = t("Przejdź do treści");
  document.getElementById("nav").setAttribute("aria-label", t("Menu główne"));
  document.getElementById("brand").append(mascotHead(36), h("span", {}, pxText("AI Tutor", 3), h("small", {}, t("angielski · lokalnie"))));
  try { await loadProfiles(); } catch (e) { toast(e.message); }
  try { S.system = await api("/api/system"); } catch (e) { /* bez statusu: tryb tekstowy domyślnie */ }
  try {
    const r = await api("/api/session/events?since=0");
    if (r.running) {   // po odświeżeniu strony wracamy do trwającej sesji
      S.session = newSession(r.kind, !!r.text_mode);
      go("#/session");
    }
  } catch (e) { /* ignore */ }
  window.addEventListener("hashchange", route);
  route();
}
document.addEventListener("DOMContentLoaded", boot);
