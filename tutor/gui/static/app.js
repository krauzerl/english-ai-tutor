// AI Language Tutor — interfejs lokalny. Cała dydaktyka jest w Pythonie; tu tylko wyświetlanie i polecenia.
"use strict";

const TOKEN = document.querySelector('meta[name="tutor-token"]').content;
const S = { pid: null, profiles: [], system: null, settings: null, seq: 0, poll: null, session: null, catalog: null };
const { icon, pxText, mascot, mascotHead, badgeArt, scene } = window.PX;

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
  try { r = await fetch(path, opt); } catch (e) { throw new Error("Brak połączenia z aplikacją. Czy okno terminala z `python main.py --gui` nadal działa?"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Błąd ${r.status}`);
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
const AREA_PL = { grammar: "gramatyka", vocabulary: "słownictwo", speaking: "mówienie", reading: "czytanie", listening: "słuchanie", writing: "pisanie" };
const areaPl = (a) => AREA_PL[a] || a;
const CAT_PL = {
  tense: "Czasy", "tense.present_simple": "Present simple", "tense.present_continuous": "Present continuous",
  "tense.past_simple": "Past simple", "tense.past_continuous": "Past continuous", "tense.present_perfect": "Present perfect",
  "tense.past_perfect": "Past perfect", "tense.future": "Przyszłość", "tense.sequence": "Następstwo czasów", aspect: "Aspekt czasownika",
  agreement: "Zgodność form", "agreement.subject_verb": "Zgodność podmiotu z orzeczeniem", "agreement.number": "Liczba pojedyncza/mnoga",
  article: "Przedimki", "article.missing": "Brak przedimka", "article.wrong": "Zły przedimek", "article.extra": "Zbędny przedimek",
  determiner: "Określniki", "determiner.quantifier": "Kwantyfikatory (much/many…)", "determiner.possessive": "Zaimki dzierżawcze",
  preposition: "Przyimki", "preposition.time": "Przyimki czasu", "preposition.place": "Przyimki miejsca", "preposition.dependent": "Stałe przyimki",
  word_order: "Szyk zdania", "word_order.question": "Szyk pytania", "word_order.adverb": "Miejsce przysłówka", "word_order.subordinate": "Pytania zależne",
  word_choice: "Dobór słowa", "word_choice.false_friend": "Fałszywi przyjaciele", "word_choice.confusable": "Słowa mylone (make/do…)",
  collocation: "Kolokacje", "collocation.verb_noun": "Czasownik + rzeczownik", "collocation.adj_noun": "Przymiotnik + rzeczownik",
  morphology: "Forma słowa", "morphology.irregular_past": "Czasowniki nieregularne", "morphology.plural": "Liczba mnoga",
  "morphology.comparative": "Stopniowanie", "morphology.word_form": "Część mowy", register: "Styl wypowiedzi", "register.formality": "Formalność",
  spelling: "Pisownia", punctuation: "Interpunkcja", capitalization: "Wielkie litery", omission: "Brakujące słowo",
  "omission.subject": "Brak podmiotu", "omission.auxiliary": "Brak operatora (do/does/did…)", "omission.copula": "Brak to be",
  l1_calque: "Kalka z polskiego", "l1_calque.make_photo": "make a photo (kalka)", "l1_calque.have_years": "I have 25 years (kalka)",
  "l1_calque.explain_me": "explain me (kalka)",
};
const catPl = (c) => CAT_PL[c] || CAT_PL[(c || "").split(".")[0]] || c;
async function catalog() {
  if (!S.catalog) S.catalog = (await q("/api/lessons")).catalog;
  return S.catalog;
}
const skillPl = (id) => (S.catalog || []).find((c) => c.skill_id === id)?.can_do_pl || id;

// ---------- nawigacja ----------
const NAV = [
  ["Nauka", [["home", "Start", "home"], ["chat", "Quick Chat", "chat"], ["lesson", "Lekcje", "lesson"], ["review", "Powtórki", "review"]]],
  ["Rozwój", [["weak", "Słabe strony", "weak"], ["placement", "Określ poziom", "level"], ["exam", "Egzaminy", "exam"]]],
  ["Ty", [["progress", "Postępy", "progress"], ["achievements", "Osiągnięcia", "trophy"], ["settings", "Ustawienia", "gear"]]],
];

function renderNav(active) {
  const nav = document.getElementById("nav");
  const live = S.session && S.session.running && active !== "session"
    ? h("a", { class: "nav-live", href: "#/session" }, `Trwa: ${KIND_TITLE[S.session.kind] || "sesja"} — wróć`) : null;
  nav.replaceChildren(...[live, ...NAV.flatMap(([group, items]) => [h("div", { class: "nav-group" }, group),
    ...items.map(([id, label, ic]) => h("a", { href: `#/${id}`, class: "nav-item", "aria-current": id === active ? "page" : null }, icon(ic, 20), label))])].filter(Boolean));
}

function setStatus() {
  const st = S.system;
  const who = S.profiles.find((p) => p.id === S.pid);
  const sys = [];
  if (st) {
    sys.push(h("div", { class: `sys ${st.ollama ? "ok" : "bad"}` }, st.ollama ? `Model: ${S.settings?.values?.chat_model || st.roles.conversation || "Ollama"}` : "Ollama nie odpowiada"));
    sys.push(h("div", { class: `sys ${st.kokoro ? "ok" : "bad"}` }, st.kokoro ? "Głos: gotowy" : "Głos: brak plików Kokoro"));
    sys.push(h("div", { class: `sys ${st.audio_error ? "bad" : "ok"}` }, st.audio_error ? "Mikrofon: niedostępny" : "Mikrofon: dostępny"));
  }
  document.getElementById("status").replaceChildren(...[
    who ? h("div", { class: "profile-chip" }, h("div", { class: "avatar", "aria-hidden": "true" }, who.name.slice(0, 1).toUpperCase()),
      h("div", {}, h("strong", {}, who.name), h("span", {}, "profil ucznia")), h("a", { href: "#/profiles" }, "Zmień")) : null,
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
  const name = h("input", { type: "text", maxlength: 40, placeholder: "np. Ola", "aria-label": "Nazwa nowego profilu" });
  const create = async () => {
    try {
      const p = await api("/api/profiles", { name: name.value }); await loadProfiles(); choosePid(p.id);
      if (location.hash === "#/home") route(); else go("#/home");
    } catch (e) { toast(e.message); }
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  return h("div", { class: "row" }, name, btn("Utwórz profil", create, "primary"));
}
async function screenProfiles(main) {
  main.append(pageHead("Kto się uczy?", "Profile", "Każdy profil ma osobną historię, postępy, osiągnięcia i ustawienia."),
    S.profiles.length ? h("div", { class: "profiles" }, S.profiles.map((p) => h("button", { type: "button", class: "profile-card", "aria-current": p.id === S.pid ? "true" : null,
      onclick: () => { choosePid(p.id); go("#/home"); } }, h("div", { class: "avatar", "aria-hidden": "true" }, p.name.slice(0, 1).toUpperCase()),
      h("div", {}, h("strong", {}, p.name), h("span", {}, p.id === S.pid ? "wybrany" : "kliknij, aby wybrać"))))) : null,
    card("Nowy profil", createForm()));
}

// ---------- Start ----------
const KIND_PL = { voice: "Rozmowa", chat: "Quick Chat", lesson: "Lekcja", review: "Powtórki", placement: "Poziom", exam: "Egzamin", drill: "Ćwiczenia" };
const KIND_GEN = { voice: "rozmowy", chat: "rozmowy", lesson: "lekcji", review: "powtórek", placement: "sprawdzania poziomu", exam: "egzaminu", drill: "ćwiczeń" };
// polska odmiana liczebnika: 1 wypowiedź, 2–4 wypowiedzi, 5+ wypowiedzi
const plural = (n, one, few, many) => `${n} ${n === 1 ? one : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many}`;
const KIND_ICON = { voice: "chat", chat: "chat", lesson: "lesson", review: "review", placement: "level", exam: "exam", drill: "weak" };

async function screenHome(main) {
  if (!S.pid) {
    main.append(h("section", { class: "hero" }, scene(),
      h("div", { class: "hero-inner" }, mascot("idle", 150),
        h("div", { class: "hero-copy" }, h("span", { class: "eyebrow" }, "Lokalny nauczyciel angielskiego"),
          h("h1", {}, h("span", { class: "sr-only" }, "Witaj!"), pxText("Witaj!", 6)),
          h("p", {}, "Rozmowy, lekcje i powtórki działają na tym komputerze. Zacznij od profilu ucznia.")))),
    card("Nowy profil", createForm()));
    return;
  }
  const [d, ac, hs, ls, pr] = await Promise.all([q("/api/home"), q("/api/achievements"), q("/api/history"), q("/api/lessons"), q("/api/progress")]);
  S.catalog = ls.catalog;
  const open = d.open_session;
  const t = hs.totals;
  const sugName = d.suggested_lesson ? skillPl(d.suggested_lesson.skill_id) : null;

  const hero = h("section", { class: "hero" }, scene(),
    h("div", { class: "hero-inner" }, mascot("idle", 132),
      h("div", { class: "hero-copy" },
        h("span", { class: "eyebrow" }, d.streak > 1 ? `Seria: ${d.streak} dni z rzędu` : "Twoja wyprawa po angielski"),
        h("h1", {}, h("span", { class: "sr-only" }, `Cześć, ${d.profile.name}!`), pxText(`Cześć, ${d.profile.name}!`, 5)),
        h("p", {}, open ? "Masz przerwaną sesję — możesz wrócić dokładnie do tego miejsca." : "Od czego zaczynamy?"))));

  const action = (cls, ic, k, title, desc, cta, onclick) => h("button", { type: "button", class: `action ${cls}`, onclick },
    h("span", { class: "k" }, icon(ic, 18), k), h("strong", {}, title), h("span", { class: "d" }, desc), h("span", { class: "go" }, `${cta} →`));
  const actions = h("section", { class: "actions-4", "aria-label": "Najważniejsze akcje" },
    action("main", "chat", "1 · Rozmowa", "Porozmawiaj z Kumką", "Swobodna rozmowa po angielsku na wybrany temat.", "Wybierz temat", () => go("#/chat")),
    open ? action("", "play", "2 · Kontynuuj", `Wróć do ${KIND_GEN[open.kind] || "sesji"}`, "Postęp przerwanej sesji jest zapisany.", "Wznów", () => resume(open))
      : action("", "lesson", "2 · Nauka", sugName || "Lekcja", d.suggested_lesson?.provisional ? "Propozycja startowa — możesz wybrać inną misję." : "Kolejna misja dobrana do Twoich wyników.", "Zacznij lekcję",
        () => startSession("lesson", { text_mode: defaultTextMode() })),
    action("", "review", "3 · Powtórka", d.due_reviews ? `${d.due_reviews} do powtórki` : "Brak zaległych", d.due_reviews ? "Sprawdź, czy pamiętasz — na nowych przykładach." : "Wrócą, gdy nadejdzie ich termin.",
      d.due_reviews ? "Powtórz teraz" : "Zobacz", () => (d.due_reviews ? startSession("review", { text_mode: defaultTextMode() }) : go("#/review"))),
    action("", "progress", "4 · Postępy", `${t.lessons_completed} lekcji · ${fmtMin(t.study_seconds)}`, `${ac.earned} z ${ac.total} odznak. Historia z zapisów na tym komputerze.`, "Zobacz postępy", () => go("#/progress")));

  // wyprawa: bieżący rozdział (pierwszy z nieopanowanymi misjami)
  const status = {};
  for (const k of ["mastered", "working", "struggling", "too_few"]) for (const r of pr.skills[k]) status[r.skill] = k;
  const levels = [...new Set(ls.catalog.map((c) => c.cefr))];
  const cur = levels.find((l) => ls.catalog.some((c) => c.cefr === l && status[c.skill_id] !== "mastered")) || levels[0];
  const inCh = ls.catalog.filter((c) => c.cefr === cur);
  const journey = cardT("star", `Rozdział ${levels.indexOf(cur) + 1}: ${CHAPTER[cur] || cur}`, h("a", { class: "more", href: "#/lesson" }, "Mapa misji"),
    h("ul", { class: "mini-list" }, inCh.map((c) => {
      const [label, tone] = STATUS[status[c.skill_id] || "new"];
      return h("li", {}, icon(AREA_ICON[c.area] || "lesson", 22), h("div", {}, h("div", { class: "t" }, c.can_do_pl), h("div", { class: "s" }, `${cur} · ${areaPl(c.area)}`)), chip(label, tone));
    })));

  const unearned = ac.items.filter((i) => !i.earned).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  const challenges = cardT("flame", "Wyzwania", h("a", { class: "more", href: "#/achievements" }, "Odznaki"),
    unearned.length ? h("ul", { class: "mini-list" }, unearned.map((i) => h("li", { class: "challenge" }, badgeArt(i.category, tierOf(ac.items, i), false, 36),
      h("div", {}, h("div", { class: "t" }, i.name), h("div", { class: "s" }, `${Math.min(i.progress, i.target)} / ${i.target} · ${i.description}`), bar(i.progress, i.target, i.name, "amber")), h("span"))))
      : note("Wszystkie wyzwania zdobyte."));
  const recent = cardT("progress", "Ostatnio", h("a", { class: "more", href: "#/progress" }, "Historia"),
    hs.sessions.length ? h("ul", { class: "mini-list" }, hs.sessions.slice(0, 3).map((s) => h("li", {}, icon(KIND_ICON[s.kind] || "chat", 22),
      h("div", {}, h("div", { class: "t" }, KIND_PL[s.kind] || s.title), h("div", { class: "s" }, `${fmtDate(s.started_at)} · ${fmtMin(s.seconds)}`)),
      h("span", { class: "s" }, s.attempts ? `${s.attempts_correct}/${s.attempts} zad.` : plural(s.user_turns, "wypowiedź", "wypowiedzi", "wypowiedzi")))))
      : note("Jeszcze nic — pierwsza rozmowa zajmie 5 minut.", "muted"));

  main.append(hero, actions, h("div", { class: "grid-2" }, journey, h("div", { class: "stack" }, challenges, recent)));
}

function resume(open) {
  const map = { chat: "chat", lesson: "lesson", placement: "placement", review: "review", exam: "exam" };
  if (open.kind === "chat") return startSession("chat", { topic: (open.plan && open.plan.topic && open.plan.topic.id) || "fd.cooking", text_mode: defaultTextMode() });
  if (open.kind === "exam") return go("#/exam");
  startSession(map[open.kind] || "lesson", { text_mode: defaultTextMode() });
}

function modeRow() {
  const cb = h("input", { type: "checkbox", id: "textmode", checked: defaultTextMode(), disabled: !voiceAvailable() });
  return h("label", { class: "check" }, cb, voiceAvailable() ? "Tryb tekstowy (bez mikrofonu i głosu)" : "Tryb tekstowy — głos niedostępny na tym komputerze");
}
const textMode = () => { const cb = document.getElementById("textmode"); return cb ? cb.checked : defaultTextMode(); };

// ---------- Quick Chat: wybór ----------
const TOPIC_TONE = { food: "amber", tech: "turq", work: "terra", hobbies: "green", travel: "turq", home: "amber", people: "terra", health: "green" };
function topicCard(t, onclick) {
  return h("button", { class: "topic", type: "button", onclick }, chip(t.category_pl, TOPIC_TONE[t.category] || ""), h("strong", {}, t.pl), h("em", { lang: "en" }, t.q));
}

async function screenChat(main) {
  let seed = null;
  const list = h("div", { class: "topic-grid", "aria-live": "polite" });
  const custom = h("input", { type: "text", maxlength: 80, placeholder: "np. my first job, football, cats…", "aria-label": "Własny temat" });
  const minutes = seg("Czas rozmowy", [["", "bez limitu"], ["5", "5"], ["10", "10"], ["15", "15"], ["20", "20"], ["30", "30"]], "");
  const corr = seg("Intensywność poprawek", [["summary", "na końcu"], ["periodic", "czasem"], ["intensive", "na bieżąco"]], S.settings?.values?.correction || "summary");
  const start = (args) => startSession("chat", { ...args, minutes: minutes.value || null, correction: corr.value, text_mode: textMode() });
  const draw = async () => {
    const ts = await q("/api/topics", seed === null ? "" : `&seed=${seed}`);
    list.replaceChildren(...ts.map((t) => topicCard(t, () => start({ topic: t.id }))));
  };
  await draw();
  const hist = await q("/api/chats").catch(() => []);
  const customGo = () => (custom.value.trim() ? start({ custom: custom.value.trim() }) : toast("Wpisz temat."));
  custom.addEventListener("keydown", (e) => { if (e.key === "Enter") customGo(); });
  main.append(
    pageHead("Rozmowa z nauczycielem", "Quick Chat", "Swobodna rozmowa po angielsku. Kliknij temat, aby zacząć od razu."),
    h("div", { class: "chat-setup" },
      h("div", { class: "stack" },
        h("div", { class: "greet" }, mascot("idle", 88), h("p", { class: "speech", lang: "en" }, "Hi! Pick a topic and let's just talk. I'll help with mistakes along the way.")),
        cardT("chat", "Tematy", h("span", { class: "more" }, btn("Wylosuj inne", () => { seed = Math.floor(Math.random() * 1e9); draw(); }, "sm quiet", "dice")), list),
        card("Własny temat", h("div", { class: "custom-topic" }, custom, btn("Rozmawiaj o tym", customGo, "primary", "play")),
          note("Temat zakończony znakiem zapytania staje się pierwszym pytaniem nauczyciela.", "muted"))),
      h("div", { class: "stack" },
        card("Ustawienia rozmowy", h("div", { class: "opts" },
          h("div", { class: "opt" }, h("span", {}, "Czas (minuty)"), minutes),
          h("div", { class: "opt" }, h("span", {}, "Poprawki"), corr),
          h("div", { class: "opt" }, h("span", {}, "Tryb"), modeRow()),
          note("Quick Chat nie nadaje statusu opanowania. Poprawki to sugestie modelu i mogą być błędne.", "muted"))),
        hist.length ? card("Ostatnie rozmowy", h("ul", { class: "mini-list" }, hist.slice(0, 5).map((c) => h("li", {}, icon("chat", 20),
          h("div", {}, h("div", { class: "t" }, (c.topics || []).join(" → ") || "—"), h("div", { class: "s" }, `${fmtDate(c.started_at)} · ${fmtMin(c.seconds_active)}`)),
          h("span", { class: "s" }, `${c.user_turns ?? 0} wyp.`))))) : null)));
}

// ---------- Lekcje: mapa misji ----------
const CHAPTER = { A1: "Pierwsze kroki", A2: "Codzienne sprawy", B1: "Samodzielność", B2: "Swoboda", C1: "Biegłość", C2: "Mistrzostwo" };
const AREA_ICON = { grammar: "lesson", vocabulary: "star", speaking: "mic", writing: "exam", reading: "lesson", listening: "chat" };
const STATUS = {
  mastered: ["Opanowana", "amber"], working: ["W toku", "green"], struggling: ["Do poprawy", "terra"], too_few: ["Rozpoczęta", "turq"], new: ["Nowa", ""],
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
    pageHead("Mapa misji", "Lekcje", `${d.catalog.length} misji z kompletem materiałów. Każda to krótkie wyjaśnienie, ćwiczenia i rozmowa.`, modeRow()),
    sug ? h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("star", 36)),
      h("div", {}, chip("Polecana misja", "amber"), h("h3", {}, skillPl(sug.skill_id)), h("p", {}, sug.reason)),
      btn("Zacznij misję", () => startSession("lesson", { text_mode: textMode() }), "primary lg", "play")) : note("Brak lekcji z gotowymi materiałami."),
    h("div", { class: "legend", "aria-label": "Legenda statusów" }, Object.values(STATUS).map(([l, c]) => chip(l, c))),
    h("div", { class: "chapters" }, Object.entries(by).map(([cefr, items], i) => h("section", { class: "chapter", "aria-labelledby": `ch-${cefr}` },
      h("div", { class: "chapter-head" }, h("div", { class: "lvl" }, cefr),
        h("div", {}, h("h2", { id: `ch-${cefr}` }, `Rozdział ${i + 1}: ${CHAPTER[cefr] || cefr}`),
          h("p", {}, `${items.filter((c) => status[c.skill_id]).length} z ${items.length} misji rozpoczętych`))),
      h("div", { class: "missions" }, items.map((c) => {
        const st = status[c.skill_id];
        const [label, tone] = STATUS[st ? st.k : "new"];
        return h("button", { type: "button", class: `mission${sug && sug.skill_id === c.skill_id ? " suggested" : ""}`, "data-status": st ? st.k : "new",
          onclick: () => startSession("lesson", { skill: c.skill_id, text_mode: textMode() }) },
          h("div", { class: "icon-box" }, icon(st && st.k === "mastered" ? "trophy" : AREA_ICON[c.area] || "lesson", 28)),
          h("strong", {}, c.can_do_pl),
          h("span", { class: "meta" }, chip(label, tone), h("span", { class: "muted" }, areaPl(c.area))),
          st ? bar(st.r.correct, st.r.attempts, `Poprawnie ${st.r.correct} z ${st.r.attempts}`) : null);
      }))))),
    note("Materiały nie są jeszcze sprawdzone przez człowieka. Status „Opanowana” nadaje wyłącznie silnik oceny.", "muted"));
}

async function screenReview(main) {
  const [home, p] = await Promise.all([q("/api/home"), q("/api/progress")]);
  await catalog();
  main.append(pageHead("Utrwalanie", "Powtórki", "Krótkie sprawdzenie na nowych przykładach. Termin każdej powtórki wyznacza harmonogram FSRS."),
    h("section", { class: "quest" }, h("div", { class: "icon-box" }, icon("review", 36)),
      h("div", {}, h("h3", {}, home.due_reviews ? `Do powtórki dziś: ${home.due_reviews}` : "Dziś nie ma zaległych powtórek"),
        h("p", {}, home.due_reviews ? "Odpowiadaj tak samo jak w lekcji. Niepewnie rozpoznana mowa nie obniża wyniku." : "Wrócą, gdy minie ich termin. Możesz w tym czasie zrobić lekcję."), modeRow()),
      home.due_reviews ? btn("Zacznij powtórki", () => startSession("review", { text_mode: textMode() }), "primary lg", "play") : btn("Przejdź do lekcji", () => go("#/lesson"), "lg")),
    p.due.length ? card("Na liście", h("ul", { class: "mini-list" }, p.due.map((s) => h("li", {}, icon("review", 20), h("div", { class: "t" }, skillPl(s)), h("span"))))) : null,
    note("Powtórki nie nadają statusu opanowania. Limit: 20 dziennie.", "muted"));
}

async function screenPlacement(main) {
  const d = await q("/api/placement");
  main.append(pageHead("Dobrowolnie", "Określ poziom", d.notice),
    h("div", { class: "grid-2" },
      card("Jak to działa", h("ul", { class: "limits" },
        h("li", {}, "Kilka krótkich pytań z gramatyki i słownictwa."), h("li", {}, "Możesz przerwać w każdej chwili i wrócić później."),
        h("li", {}, "Ponowne sprawdzenie nie kasuje historii nauki."), h("li", {}, "Niepewne rozpoznanie mowy nie obniża wyniku.")),
      table(["Obszar", "Pytania w banku"], d.areas.map((a) => [areaPl(a.area), a.items])),
      h("div", { class: "row" }, modeRow(), btn(d.results.length ? "Sprawdź ponownie" : "Zacznij", () => startSession("placement", { text_mode: textMode() }), "primary lg", "level"))),
      card("Wyniki (szacunek wstępny)", d.results.length ? h("ul", { class: "mini-list" }, d.results.map((r) => h("li", {}, icon("level", 22),
        h("div", {}, h("div", { class: "t" }, `${areaPl(r.area)}: ${r.label || "—"}`), h("div", { class: "s" }, `${fmtDate(r.measured_at)} · ${r.status}${r.notice ? " · " + r.notice : ""}`)), h("span"))))
        : note("Jeszcze nie sprawdzano poziomu. Wynik to szacunek, nie certyfikat CEFR.", "muted"))));
}

const REL = {
  "potwierdzony ćwiczeniami": ["ok", "Potwierdzony ćwiczeniami"],
  "sugestia modelu": ["warn", "Sugestia modelu"],
  "niepewna transkrypcja STT": ["stt", "Możliwy błąd rozpoznawania mowy"],
  "za mało danych": ["none", "Za mało danych"],
};
async function screenWeak(main) {
  const d = await q("/api/weakspots");
  await catalog();
  const head = pageHead("Dziennik błędów", "Słabe strony", "Każdy wpis ma etykietę wiarygodności. „Sugestia modelu” nie jest potwierdzonym błędem.");
  if (!d.has_data) {
    main.append(head, h("div", { class: "empty" }, mascot("idle", 72), h("div", {}, h("p", {}, "Jeszcze nic tu nie ma. Wpisy pojawią się po rozmowach, lekcjach i powtórkach."), note(d.stt_uncertain.note, "muted"))));
    return;
  }
  main.append(head,
    h("div", { class: "grid-2" },
      h("div", { class: "stack" },
        d.errors.length ? h("div", { class: "weak-list" }, d.errors.map((e, i) => {
          const [cls, label] = REL[e.reliability] || ["none", e.reliability];
          const t = e.trend || {};
          return h("article", { class: "weak" },
            h("header", {}, h("strong", {}, `${i + 1}. ${catPl(e.category)}`), h("span", { class: `badge ${cls}` }, label)),
            e.example && cls !== "stt" ? h("p", { class: "example" }, e.correction ? fixLine(e.example, e.correction) : h("span", { lang: "en" }, e.example)) : null,
            h("p", { class: "muted" }, `${e.count}× · ostatnio ${fmtDate(e.last_seen)} · trend: ${t.direction || "za mało danych"}`),
            e.skills.length ? h("div", {}, btn("Ćwicz to", () => startSession("drill", { target: String(i + 1), text_mode: defaultTextMode() }), "primary", "play")) : note("Brak materiałów do ćwiczeń dla tej kategorii.", "muted"));
        })) : null,
        note("Trend pokazujemy dopiero przy co najmniej 5 wypowiedziach w obu okresach (14 dni).", "muted")),
      h("div", { class: "stack" },
        d.weak_skills.length ? card("Umiejętności poniżej połowy", h("ul", { class: "mini-list" }, d.weak_skills.map((w) => h("li", {}, icon("weak", 20),
          h("div", {}, h("div", { class: "t" }, skillPl(w.skill)), h("div", { class: "s" }, `${w.correct}/${w.attempts} poprawnie`)),
          btn("Ćwicz", () => startSession("drill", { target: w.skill, text_mode: defaultTextMode() }), "sm"))))) : null,
        d.vocabulary.length ? card("Słowa do utrwalenia", table(["Słowo", "Pomyłki"], d.vocabulary.map((w) => [w.term, w.misses]))) : null,
        card("Niepewne rozpoznanie mowy", h("p", {}, `${d.stt_uncertain.count} — ${d.stt_uncertain.note}`)),
        d.due_reviews.length ? card("Do powtórki", h("p", {}, d.due_reviews.map(skillPl).join(", ")), btn("Zacznij powtórki", () => go("#/review"))) : null)));
}

async function screenExam(main) {
  const paths = await q("/api/exams");
  main.append(pageHead("Ścieżki egzaminacyjne", "Egzaminy", "Ćwiczenia w formacie egzaminu. Wynik ćwiczeń nie jest prognozą wyniku egzaminu."));
  for (const p of paths) {
    const r = p.readiness;
    main.append(cardT("exam", p.name, null,
      note(p.disclaimer, "muted"),
      table(["Część", "Materiały", "Wynik ćwiczeń", "Stan"], r.sections.map((s) => {
        const cov = p.coverage.find((c) => c.section === s.section) || {};
        return [s.name, cov.status === "ok" ? `${cov.items} zadań` : (cov.note || "brak"), s.scored ? `${s.correct}/${s.scored}` : "—", s.label];
      })),
      h("ul", { class: "limits" }, [...new Set(r.limits || [])].filter((l) => l !== p.disclaimer).map((l) => h("li", {}, l))),
      p.speaking_topics.length ? h("div", {}, h("h3", { class: "card-title" }, "Mówienie (w Quick Chat)"), h("div", { class: "row" },
        p.speaking_topics.map((t) => btn(t.pl, () => startSession("chat", { custom: t.q.slice(0, 80), text_mode: defaultTextMode() }), "sm quiet", "chat")))) : null,
      h("div", { class: "row" }, modeRow(), btn("Ćwicz tę ścieżkę", () => startSession("exam", { path: p.id, text_mode: textMode() }), "primary", "play"))));
  }
  main.append(note("Matura i Cambridge: przygotowane w architekturze, bez materiałów — nie są jeszcze dostępne.", "muted"));
}

async function screenProgress(main) {
  const [p, hs, ac] = await Promise.all([q("/api/progress"), q("/api/history"), q("/api/achievements")]);
  await catalog();
  const t = hs.totals;
  const small = (n) => (n < 5 ? " (mała próba)" : "");
  const groups = [["mastered", "Opanowane", "amber"], ["working", "W toku", "green"], ["struggling", "Wymagają pracy", "terra"], ["too_few", "Za mało prób", "turq"]];
  const status = { ended: "zakończona", paused: "przerwana", active: "trwa", abandoned: "porzucona" };
  main.append(
    pageHead("Dziennik nauki", "Postępy", "Wszystko pochodzi z bazy na tym komputerze. Czas nauki to przybliżenie z odstępów między zapisami."),
    h("div", { class: "stats" },
      stat("Czas nauki", fmtMin(t.study_seconds)), stat("Sesje", t.sessions), stat("Ukończone lekcje", t.lessons_completed),
      stat("Powtórki", t.reviews_done), stat("Twoje wypowiedzi", t.user_turns), stat("Odznaki", `${ac.earned}/${ac.total}`)),
    h("div", { class: "grid-2" },
      card("Umiejętności", ...groups.map(([k, label, tone]) => p.skills[k].length ? h("div", { class: "stack" },
        h("h3", { class: "card-title" }, chip(label, tone), h("span", { class: "muted" }, String(p.skills[k].length))),
        h("ul", { class: "mini-list" }, p.skills[k].map((r) => h("li", {}, icon("lesson", 20),
          h("div", {}, h("div", { class: "t" }, skillPl(r.skill)), bar(r.correct, r.attempts, `${r.correct} z ${r.attempts}`)),
          h("span", { class: "s" }, `${r.correct}/${r.attempts}${small(r.attempts)}`))))) : null),
        Object.values(p.skills).every((x) => !x.length) ? note("Jeszcze nie ma ocenionych zadań.", "muted") : null),
      h("div", { class: "stack" },
        card("Poziom (dobrowolne sprawdzenie)", h("ul", { class: "mini-list" }, p.competence.map((c) => h("li", {}, icon("level", 20),
          h("div", {}, h("div", { class: "t" }, areaPl(c.area)), h("div", { class: "s" }, c.measured_at ? fmtDate(c.measured_at) : "")), h("span", { class: "s" }, c.label || c.state))))),
        p.changes.length ? card("Zmiany między sesjami", h("ul", { class: "mini-list" }, p.changes.map((c) => h("li", {}, icon("progress", 20),
          h("div", { class: "t" }, skillPl(c.skill)), h("span", { class: "s" }, `${c.previous[0]}/${c.previous[1]} → ${c.latest[0]}/${c.latest[1]}${small(c.latest[1])}`))))) : null)),
    card("Historia sesji", hs.sessions.length ? table(["Data", "Rodzaj", "Status", "Czas", "Wypowiedzi", "Zadania"],
      hs.sessions.map((s) => [fmtDate(s.started_at), KIND_PL[s.kind] || s.kind, status[s.status] || s.status, fmtMin(s.seconds), s.user_turns, s.attempts ? `${s.attempts_correct}/${s.attempts}` : "—"])) : note("Brak sesji.")));
}

// ---------- Osiągnięcia ----------
const CAT = { regularity: "Regularność", talk_time: "Czas rozmów", lessons: "Lekcje", reviews: "Powtórki", improvement: "Poprawa", weakspots: "Słabe strony", challenges: "Wyzwania", milestones: "Kamienie milowe", exams: "Egzaminy", mastered: "Opanowane umiejętności" };
const TIER_PL = ["Brąz", "Srebro", "Złoto"];
// Próg w kategorii (rosnąco wg celu) wyznacza kolor ramki odznaki: brąz, srebro, złoto.
function tierOf(items, item) {
  const same = items.filter((i) => i.category === item.category).sort((a, b) => a.target - b.target);
  return same.length < 2 ? 2 : Math.min(2, Math.floor(same.indexOf(item) * 3 / same.length));
}

async function screenAchievements(main) {
  const d = await q("/api/achievements");
  if (d.new && d.new.length) toast(`Nowe osiągnięcie: ${d.new.map((n) => n.name).join(", ")}`);
  let filter = "all";
  const by = {};
  d.items.forEach((i) => (by[i.category] = by[i.category] || []).push(i));
  const shelves = h("div", { class: "stack" });
  const draw = () => {
    shelves.replaceChildren(...Object.entries(by).map(([cat, items]) => {
      const shown = items.filter((i) => filter === "all" || (filter === "earned" ? i.earned : !i.earned));
      if (!shown.length) return null;
      return h("section", { class: "shelf", "aria-labelledby": `cat-${cat}` },
        h("div", { class: "shelf-head" }, badgeArt(cat, 2, items.some((i) => i.earned), 28), h("h2", { id: `cat-${cat}` }, CAT[cat] || cat),
          h("span", { class: "count" }, `${items.filter((i) => i.earned).length}/${items.length}`)),
        h("div", { class: "badges" }, shown.map((i) => {
          const tier = tierOf(d.items, i);
          return h("article", { class: i.earned ? "badge-card earned" : "badge-card locked", "aria-label": `${i.name}: ${i.earned ? "zdobyte" : "niezdobyte"}` },
            chip(TIER_PL[tier], i.earned ? "amber" : ""),
            i.earned ? null : h("span", { class: "lockmark", "aria-hidden": "true" }, icon("lock", 20)),
            badgeArt(i.category, tier, i.earned, 80),
            h("strong", {}, i.name), h("span", { class: "desc" }, i.description),
            i.earned ? h("span", { class: "when" }, `Zdobyte ${fmtDay(i.earned_at)}`)
              : h("div", { class: "prog" }, bar(i.progress, i.target, `${i.name}: ${Math.min(i.progress, i.target)} z ${i.target}`, "amber"), `${Math.min(i.progress, i.target)} / ${i.target}`));
        })));
    }).filter(Boolean));
  };
  const near = d.items.filter((i) => !i.earned && i.progress > 0).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  main.append(
    h("section", { class: "trophy-hero" }, icon("trophy", 84),
      h("div", {}, h("span", { class: "eyebrow" }, "Sala trofeów"),
        h("h1", {}, h("span", { class: "sr-only" }, "Osiągnięcia"), pxText("Osiągnięcia", 5)),
        h("p", {}, d.note || "Odznaki nagradzają regularną pracę. Nie oznaczają opanowania języka."),
        bar(d.earned, d.total, `Zdobyte ${d.earned} z ${d.total}`, "amber")),
      h("div", { class: "counter" }, h("strong", {}, `${d.earned}/${d.total}`), h("span", {}, "zdobytych odznak"))),
    near.length ? cardT("flame", "Najbliżej zdobycia", null,
      h("div", { class: "near" }, near.map((i) => h("div", { class: "badge-row" }, badgeArt(i.category, tierOf(d.items, i), false, 48),
        h("div", {}, h("strong", {}, i.name), h("div", { class: "muted" }, i.description), bar(i.progress, i.target, i.name, "amber")))))) : null,
    h("div", { class: "row" }, seg("Filtr odznak", [["all", "Wszystkie"], ["earned", "Zdobyte"], ["locked", "Do zdobycia"]], filter, (v) => { filter = v; draw(); })),
    shelves);
  draw();
}

// ---------- Ustawienia ----------
const SET_LABELS = {
  chat_model: "Model rozmowy", tts_voice: "Głos nauczyciela", speed: "Tempo mowy", correction: "Poprawki w rozmowie",
  session_minutes: "Dzienny czas nauki (min)", io_mode: "Tryb domyślny", mic_mode: "Mikrofon",
  input_device: "Mikrofon (urządzenie)", output_device: "Głośnik (urządzenie)", stt_model: "Rozpoznawanie mowy",
  allow_unreviewed: "Używaj materiałów niesprawdzonych przez człowieka", conversation_mode: "Domyślna aktywność", target_lang: "Język nauki",
};
const SET_GROUPS = [["Rozmowa i nauka", ["chat_model", "correction", "conversation_mode", "session_minutes", "allow_unreviewed", "target_lang"]],
  ["Głos i dźwięk", ["io_mode", "tts_voice", "speed", "mic_mode", "input_device", "output_device"]]];
const CHOICE_LABELS = { summary: "podsumowanie na końcu", periodic: "co jakiś czas", intensive: "na bieżąco", ptt: "kliknij, aby mówić", auto: "automatyczny", voice: "głosowy", text: "tekstowy", quick_chat: "Quick Chat", lesson: "lekcja", en: "angielski" };
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
      input = h("select", {}, h("option", { value: "default", selected: val === "default" }, "systemowe"), st.devices.map((v) => h("option", { value: v, selected: v === val }, v)));
    } else if (spec.type === "choice") input = h("select", {}, spec.choices.map((c) => h("option", { value: c, selected: String(c) === String(val) },
      key === "chat_model" ? `${c}${st && st.models.includes(c) ? "" : " (nie pobrany)"}` : (CHOICE_LABELS[c] || c))));
    else if (spec.type === "float") input = h("input", { type: "number", min: spec.min, max: spec.max, step: 0.05, value: val });
    else if (spec.type === "bool") input = h("input", { type: "checkbox", checked: !!val });
    else return null;
    fields[key] = input;
    return h("label", { class: "field" }, h("span", {}, SET_LABELS[key] || key), input);
  };
  const save = async () => {
    const changes = {};
    for (const [k, el] of Object.entries(fields)) changes[k] = el.type === "checkbox" ? el.checked : el.value;
    try { S.settings.values = await api("/api/settings", { pid: S.pid, changes }); toast("Zapisano ustawienia."); setStatus(); }
    catch (e) { toast(e.message); }
  };
  main.append(pageHead("Profil ucznia", "Ustawienia", "Zmiany dotyczą tylko wybranego profilu."),
    ...SET_GROUPS.map(([title, keys]) => card(title, h("form", { class: "settings", onsubmit: (e) => e.preventDefault() }, keys.map(field)))),
    h("div", { class: "row" }, btn("Zapisz ustawienia", save, "primary lg", "check")),
    note("Model oceny zostaje bez zmian (Qwen3 8B): jego zmiana wymaga kontroli jakości. Model rozmowy musi być pobrany w Ollamie.", "muted"),
    card("Ten komputer", table(["Element", "Stan"], st ? [
      ["Ollama", st.ollama ? "działa" : "nie odpowiada — uruchom `ollama serve`"], ["Pobrane modele", st.models.join(", ") || "—"],
      ["Model oceny", st.roles.evaluation || "—"], ["Głos (Kokoro)", st.kokoro ? `gotowy, ${st.voices.length} głosów` : "brak plików modelu"],
      ["Audio", st.audio_error ? `niedostępne: ${st.audio_error}` : st.devices.join("; ")]] : [])));
}

// ---------- sesja ----------
const KIND_TITLE = { chat: "Quick Chat", lesson: "Lekcja", placement: "Określ poziom", review: "Powtórki", drill: "Ćwiczenia słabej strony", exam: "Ćwiczenia egzaminacyjne" };
const STATE_PL = { listening: "Słucham…", thinking: "Myślę…", speaking: "Mówię…", turn: "Twoja kolej", idle: "Sesja zakończona", connecting: "Łączę…",
  encouraging: "Spróbuj jeszcze raz", success: "Dobrze!", explaining: "Wyjaśniam", error: "Problem" };

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
    connecting: "Uruchamiam nauczyciela…",
    listening: "Mów teraz. Kliknij Stop, gdy skończysz.",
    thinking: task ? "Sprawdzam odpowiedź…" : "Układam odpowiedź…",
    speaking: "Nauczyciel mówi. Kliknij mikrofon, aby przerwać i odpowiedzieć.",
    success: "Dobrze! Za chwilę kolejny krok.",
    encouraging: "Prawie. Spróbuj jeszcze raz — wskazówka poniżej.",
    explaining: "Przeczytaj krótkie wyjaśnienie. Pierwsze zadanie zaraz się pojawi.",
    idle: "Sesja zakończona. Wyniki są zapisane.",
    error: s.error || "Coś poszło nie tak.",
    turn: task ? (hasOpts ? "Wybierz odpowiedź albo powiedz ją." : (s.text ? "Napisz odpowiedź na zadanie." : "Odpowiedz: kliknij mikrofon albo napisz."))
      : (s.text ? "Twoja kolej: napisz odpowiedź." : "Twoja kolej: kliknij Mów i odpowiedz."),
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
  if (!s) { main.append(h("div", { class: "empty" }, mascot("idle", 72), h("div", {}, h("p", {}, "Brak aktywnej sesji."), btn("Na start", () => go("#/home"), "primary")))); return; }
  s.layout = chatLayout(s) ? "chat" : "task";
  const send = async (text) => {
    try { await api("/api/session/send", { text }); if (text) { s.waiting = true; s.hint = null; drawSide(); } } catch (e) { toast(e.message); }
  };
  const input = h("input", { type: "text", id: "say", maxlength: 500, lang: "en", placeholder: s.text ? "Napisz po angielsku…" : "Albo napisz po angielsku…", "aria-label": "Twoja odpowiedź" });
  const submit = () => {
    const t = input.value.trim(); if (!t) return; input.value = "";
    if (s.layout === "task") { drawEvent({ kind: "you", text: t, seq: -1 }, true); s.answered = t; }   // silnik nie powtarza odpowiedzi
    send(t);
  };
  S.answer = (t) => { input.value = t; submit(); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const composer = h("div", { class: "composer" }, input, btn("Wyślij", submit, "primary"));
  const mic = () => (s.text ? null : h("button", { type: "button", class: "mic-big", id: "micbtn", "aria-label": "Mów", onclick: () => send("") }, icon("mic", 34), h("span", { class: "mic-label" }, "Mów")));
  const stop = btn(s.kind === "chat" ? "Zakończ rozmowę" : "Przerwij i zapisz", () => api("/api/session/stop", {}).catch((e) => toast(e.message)), "danger block end");
  const log = h("div", { class: "log", id: "log", "aria-live": "polite", "aria-label": "Przebieg rozmowy" });

  if (s.layout === "chat") {
    const tools = s.kind === "chat"
      ? [["Powtórz", "Could you repeat that, please?"], ["Wyjaśnij prościej", "Could you explain that in simpler words?"], ["Zmień temat", "Can we change the topic?", "wide"]]
      : [["Powtórz", "Could you repeat that, please?"], ["Wyjaśnij prościej", "Could you explain that in simpler words?"]];
    main.append(h("div", { class: "session chat" },
      h("aside", { class: "stage", id: "stage", "aria-label": "Nauczyciel" },
        mascot("idle", 150), h("span", { class: "state-label", id: "sstate", "data-state": "connecting", role: "status" }, STATE_PL.connecting),
        h("p", { class: "next", id: "next" }), mic(),
        h("div", { class: "topic-now", id: "topicnow" }),
        h("div", { class: "tools" }, tools.map(([l, t, c]) => btn(l, () => send(t), `sm ${c || ""}`))), stop),
      h("section", { class: "convo", "aria-label": "Rozmowa" },
        h("div", { class: "convo-head" }, h("h1", {}, s.kind === "chat" ? "Quick Chat" : "Rozmowa po lekcji"), h("span", { class: "muted" }, s.text ? "tryb tekstowy" : "tryb głosowy")),
        log,
        s.text ? composer : h("details", { class: "write-toggle" }, h("summary", {}, "Wolę napisać"), composer))));
  } else {
    const tools = ["exam", "placement"].includes(s.kind) ? [["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?"]]
      : [["Podpowiedź", "Could you explain, please?"], ["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?", "wide"]];
    main.append(h("div", { class: "session task" },
      h("div", { class: "task-main" },
        h("header", { class: "mission-bar" }, icon(KIND_ICON[s.kind] || "lesson", 36),
          h("div", {}, h("h1", {}, KIND_TITLE[s.kind] || s.kind), h("div", { class: "goal-line", id: "goalline" }), h("div", { id: "steps" }))),
        h("div", { class: "now", id: "now", role: "status" }),
        h("section", { class: "task-card", id: "taskcard", "aria-live": "polite" }),
        h("div", { class: "answer", id: "answer" }, mic(), h("div", { class: "composer paper" }, input, btn("Wyślij", submit, "primary"))),
        h("div", { id: "verdict", "aria-live": "polite" }),
        h("details", { class: "transcript" }, h("summary", {}, "Przebieg sesji"), log)),
      h("aside", { class: "coach", id: "stage", "aria-label": "Nauczyciel" },
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
    if (k === "info" && ev.text.trim().startsWith("Teraz krótka rozmowa")) s.phase = "chat";
    if (["you", "tutor", "prompt", "end", "heard"].includes(k)) s.recording = false;
    if (["you", "heard"].includes(k)) s.waiting = true;
    if (["tutor", "task", "feedback", "hint", "prompt", "error", "end", "goal", "correction_head"].includes(k)) s.waiting = false;
    if (k === "tutor") { s.speaking = true; s.said = (s.lastKind === "tutor" && s.said ? `${s.said} ` : "") + ev.text; }
    if (["prompt", "listening", "end", "you"].includes(k)) s.speaking = false;
    if (k === "error") s.error = ev.text;
    if (k === "info" && ev.text.startsWith("Quick Chat — temat:")) s.topic = ev.text.replace("Quick Chat — temat:", "").split("(")[0].trim().replace(/\.$/, "");
    if (k === "notice" && ev.text.startsWith("nowy temat:")) s.topic = ev.text.replace("nowy temat:", "").trim();
    if (!["prompt", "metric", "listening"].includes(k)) s.lastKind = k;
  }
  const log = document.getElementById("log");
  if (!log) return;
  if (["prompt", "start", "metric", "listening", "recording"].includes(k)) return;
  if (k === "info" && /^(\[Enter\]|Profil:|Quick Chat — temat:)/.test(ev.text)) return;        // diagnostyka i instrukcje CLI
  if (k === "goal" && s.layout === "task") return;                                              // cel ma własne miejsce
  const last = log.lastElementChild;
  if (k === "tutor" && last && last.classList.contains("tutor") && last.dataset.seq == ev.seq - 1) {   // jedna wypowiedź, kilka zdań
    last.querySelector(".bubble").textContent += " " + ev.text; last.dataset.seq = ev.seq; log.scrollTop = log.scrollHeight; return;
  }
  let el;
  if (k === "tutor") el = h("div", { class: "msg tutor" }, h("div", { class: "avatar-s", "aria-hidden": "true" }, mascotHead(30)), h("div", {}, h("b", {}, "Kumka"), h("p", { class: "bubble", lang: "en" }, ev.text)));
  else if (k === "you") el = h("div", { class: "msg you" }, h("b", {}, "Ty"), h("p", { lang: "en" }, ev.text));
  else if (k === "task") el = h("div", { class: "msg task" }, h("b", {}, `Zadanie ${ev.index}/${ev.total}`), h("pre", { lang: "en" }, ev.text));
  else if (k === "goal") el = h("div", { class: "msg goal" }, h("b", {}, "Cel"), rich(ev.text));
  else if (k === "feedback") el = h("div", { class: `msg feedback${ev.text.startsWith("✓") ? " ok" : /^(✗|Poprawna)/.test(ev.text) ? " no" : ""}` }, h("pre", {}, ev.text.trim()));
  else if (k === "hint") el = h("div", { class: "msg hint" }, h("b", {}, "Wskazówka"), h("p", {}, ev.text));
  else if (k === "correction_head") el = h("div", { class: "msg correction-head" }, "Do poprawy w tej rozmowie (sugestie modelu)");
  else if (k === "correction") el = h("div", { class: "msg correction" }, h("div", { class: "fix" }, fixLine(ev.span, ev.fix)),
    ev.why ? h("div", { class: "why" }, ev.why) : null, ev.stt ? h("div", { class: "why" }, "Możliwe, że źle usłyszałem — sprawdź, czy tak powiedziałeś/aś.") : null);
  else if (k === "heard") el = h("div", { class: "msg heard" }, `Rozpoznano: ${ev.text}`);
  else if (k === "error") el = h("div", { class: "msg error", role: "alert" }, h("b", {}, "Problem"), h("p", {}, ev.text));
  else if (k === "end") el = h("div", { class: "msg sys" }, ev.code ? "Sesja zakończona z błędem." : "Sesja zamknięta. Wyniki zapisano.");
  else el = h("div", { class: `msg ${k}` }, h("pre", {}, ev.text.trim()));
  el.dataset.seq = ev.seq;
  log.append(el);
  log.scrollTop = log.scrollHeight;
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
  if (mic) { mic.classList.toggle("on", s.recording); mic.setAttribute("aria-label", s.recording ? "Stop — zakończ nagrywanie" : "Mów"); mic.querySelector(".mic-label").textContent = s.recording ? "Stop" : "Mów"; }
  const end = document.querySelector(".end");
  if (end && end.tagName === "BUTTON" && !s.running) end.replaceWith(h("div", { class: "row end" }, btn("Zobacz postępy", () => go("#/progress"), "primary"), btn("Na start", () => go("#/home"))));
  if (s.layout === "chat") {
    document.getElementById("next").textContent = nextText(s, state);
    const min = Math.floor((Date.now() - s.started) / 60000);
    document.getElementById("topicnow").replaceChildren(h("span", {}, s.kind === "chat" ? "Temat" : "Rozmowa po lekcji"),
      h("strong", {}, s.kind === "chat" ? (s.topic || "…") : (s.goal || "…")), h("div", { class: "muted" }, `${min} min`));
    return;
  }
  const now = document.getElementById("now");
  now.dataset.state = state; now.textContent = nextText(s, state);
  document.getElementById("goalline").textContent = s.goal || "";
  if (s.task) document.getElementById("steps").replaceChildren(h("div", { class: "steps", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": s.task.total, "aria-valuenow": s.task.index - 1, "aria-label": `Zadanie ${s.task.index} z ${s.task.total}` },
    Array.from({ length: s.task.total }, (_, i) => h("i", { class: i < s.task.index - 1 ? "done" : i === s.task.index - 1 ? "now" : "" }))));
  const said = document.getElementById("said");
  if (s.said) { said.hidden = false; said.replaceChildren(h("b", {}, "Kumka mówi"), h("span", { lang: "en" }, s.said)); }
  const ex = document.getElementById("explainbox");
  const body = s.goalText ? s.goalText.split("\n").slice(1).join("\n").trim() : "";
  if (body && !ex.firstChild) ex.append(h("details", { class: "explain", open: true }, h("summary", {}, "Wyjaśnienie"), rich(lessonText(body))));
  const card = document.getElementById("taskcard");
  const key = s.task ? String(s.task.seq) : "none";
  if (card.dataset.key !== key) {
    card.dataset.key = key;
    if (s.task) {
      const opts = [...s.task.text.matchAll(/^\s+\d+\.\s+(.+)$/gm)].map((m) => m[1].trim());
      const stem = s.task.text.replace(/\n\s+\d+\.\s+.+/g, "");
      card.replaceChildren(...[h("span", { class: "k" }, `Zadanie ${s.task.index} z ${s.task.total}`), h("pre", { class: "stem", lang: "en" }, stem),
        opts.length ? h("div", { class: "options" }, opts.map((o, i) => h("button", { type: "button", class: "btn", onclick: () => S.answer(o) }, h("span", { class: "n" }, String(i + 1)), o))) : null].filter(Boolean));
    } else card.replaceChildren(h("span", { class: "k" }, "Za chwilę"), h("p", { class: "stem" }, "Pierwsze zadanie pojawi się za moment."));
  }
  card.querySelectorAll(".options button").forEach((b) => { b.disabled = !s.running; });
  const v = verdictOf(s);
  document.getElementById("verdict").replaceChildren(...[
    s.heard ? h("div", { class: "verdict" }, h("b", {}, "Rozpoznano"), h("span", { lang: "en" }, s.heard))
      : s.answered && (s.feedback || s.hint) ? h("div", { class: "verdict" }, h("b", {}, "Twoja odpowiedź"), h("span", { lang: "en" }, s.answered)) : null,
    v === "ok" ? h("div", { class: "verdict ok" }, h("b", {}, "Dobrze"), s.feedback) : null,
    v === "no" ? h("div", { class: "verdict no" }, h("b", {}, "Jeszcze nie"), s.feedback) : null,
    v === "hint" ? h("div", { class: "verdict hint" }, h("b", {}, "Wskazówka"), s.hint) : null,
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
  main.replaceChildren(h("p", { class: "loading" }, "Wczytuję…"));
  if (!S.pid && !["home", "profiles"].includes(id)) { go("#/home"); return; }
  const frag = h("div", { class: "screen" });
  const append = frag.append.bind(frag);
  frag.append = (...kids) => append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  try {
    if (S.pid && !S.settings) S.settings = await q("/api/settings").catch(() => null);
    await fn(frag);
  } catch (e) {
    frag.replaceChildren(h("div", { class: "empty" }, mascot("thinking", 72), h("div", {}, h("p", {}, e.message), btn("Spróbuj ponownie", route, "primary"))));
  }
  main.replaceChildren(frag);
  setStatus();
}

async function boot() {
  document.getElementById("brand").append(mascotHead(36), h("span", {}, pxText("AI Tutor", 3), h("small", {}, "angielski · lokalnie")));
  try { await loadProfiles(); } catch (e) { toast(e.message); }
  api("/api/system").then((st) => { S.system = st; setStatus(); }).catch(() => {});
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
