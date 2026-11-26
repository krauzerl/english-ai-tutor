// AI Language Tutor — interfejs lokalny. Cała dydaktyka jest w Pythonie; tu tylko wyświetlanie i polecenia.
"use strict";

const TOKEN = document.querySelector('meta[name="tutor-token"]').content;
const S = { pid: null, profiles: [], system: null, settings: null, seq: 0, poll: null, session: null };
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
  try { r = await fetch(path, opt); } catch (e) { throw new Error("Brak połączenia z aplikacją (czy serwer działa?)"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Błąd ${r.status}`);
  return data;
}
const q = (path, extra = "") => api(`${path}?pid=${S.pid}${extra}`);

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { t.hidden = true; }, 6000);
}

function fmtDate(s) { return s ? s.replace("T", " ").slice(0, 16) : "—"; }
function fmtDay(s) { return s ? s.slice(0, 10) : "—"; }
function fmtMin(sec) { const m = Math.round((sec || 0) / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; }

// ---------- komponenty ----------
function btn(label, onclick, cls = "", ic = null) { return h("button", { class: `btn ${cls}`, onclick, type: "button" }, ic ? icon(ic, 18) : null, label); }
function card(title, ...kids) { return h("section", { class: "card" }, title ? h("h2", { class: "card-title" }, title) : null, ...kids); }
const panel = card;
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
// Bezpieczne, minimalne formatowanie wyjaśnień (nagłówki ##, listy -, `kod`) — bez innerHTML.
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
  const rows = [];
  const who = S.profiles.find((p) => p.id === S.pid);
  if (who) rows.push(h("div", { class: "sys ok" }, `Profil: ${who.name}`));
  if (st) {
    rows.push(h("div", { class: `sys ${st.ollama ? "ok" : "bad"}` }, st.ollama ? `Ollama · ${S.settings?.values?.chat_model || st.roles.conversation}` : "Ollama nie działa (ollama serve)"));
    rows.push(h("div", { class: `sys ${st.kokoro ? "ok" : "bad"}` }, st.kokoro ? "Głos: Kokoro" : "Głos: brak plików (tryb tekstowy)"));
    rows.push(h("div", { class: `sys ${st.audio_error ? "bad" : "ok"}` }, st.audio_error ? "Audio: niedostępne" : `Audio: ${st.devices.length} urządzeń`));
  }
  document.getElementById("status").replaceChildren(...rows);
}

function voiceAvailable() { return S.system && S.system.kokoro && !S.system.audio_error; }
function defaultTextMode() { return !voiceAvailable() || S.settings?.values?.io_mode === "text"; }

// ---------- profil ----------
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
function profileBox(open = false) {
  const sel = h("select", { "aria-label": "Profil ucznia", onchange: (e) => { choosePid(Number(e.target.value)); route(); } },
    S.profiles.map((p) => h("option", { value: p.id, selected: p.id === S.pid }, p.name)));
  const name = h("input", { type: "text", maxlength: 40, placeholder: "Imię nowego ucznia", "aria-label": "Nazwa nowego profilu" });
  const create = async () => {
    try { const p = await api("/api/profiles", { name: name.value }); await loadProfiles(); choosePid(p.id); route(); }
    catch (e) { toast(e.message); }
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  return h("details", { class: "profile-switch", open: open || null }, h("summary", {}, "Zmień lub dodaj profil"),
    S.profiles.length ? h("label", { class: "field-inline" }, "Uczeń", sel) : null,
    h("div", { class: "row" }, name, btn("Utwórz profil", create, "primary")));
}

// ---------- Home ----------
const KIND_PL = { voice: "Rozmowa", chat: "Quick Chat", lesson: "Lekcja", review: "Powtórki", placement: "Poziom", exam: "Egzamin", drill: "Ćwiczenia" };
const KIND_ICON = { voice: "chat", chat: "chat", lesson: "lesson", review: "review", placement: "level", exam: "exam", drill: "weak" };

async function screenHome(main) {
  if (!S.pid) {
    main.append(h("section", { class: "hero" }, scene(),
      h("div", { class: "hero-inner" }, mascot("idle", 140),
        h("div", { class: "hero-copy" }, h("h1", {}, h("span", { class: "sr-only" }, "Witaj!"), pxText("Witaj!", 6)),
          h("p", {}, "Lokalny nauczyciel angielskiego. Rozmowy, lekcje i powtórki działają na tym komputerze. Zacznij od profilu ucznia.")))),
    card("Nowy profil", profileBox(true)));
    return;
  }
  const [d, ac, hs, ls, topics] = await Promise.all([q("/api/home"), q("/api/achievements"), q("/api/history"), q("/api/lessons"), q("/api/topics").catch(() => [])]);
  const lessonName = (id) => (ls.catalog.find((c) => c.skill_id === id) || {}).can_do_pl || id;
  const open = d.open_session;

  const hero = h("section", { class: "hero" }, scene(),
    h("div", { class: "hero-inner" }, mascot("idle", 132),
      h("div", { class: "hero-copy" },
        h("span", { class: "eyebrow" }, d.streak > 1 ? `Seria: ${d.streak} dni z rzędu` : "Twoja przygoda z angielskim"),
        h("h1", {}, h("span", { class: "sr-only" }, `Cześć, ${d.profile.name}!`), pxText(`Cześć, ${d.profile.name}!`, 5)),
        h("p", {}, d.last_session ? `Ostatnio: ${(KIND_PL[d.last_session.kind] || d.last_session.title).toLowerCase()}, ${fmtDate(d.last_session.started_at)}.` : "Wybierz, od czego zaczynamy."),
        h("div", { class: "hero-actions" },
          btn("Szybka rozmowa", () => { location.hash = "#/chat"; }, "primary lg", "chat"),
          btn(open ? "Wznów sesję" : "Kontynuuj lekcję", () => (open ? resume(open) : startSession("lesson", { text_mode: defaultTextMode() })), "gold lg", "play")))));

  const quests = h("section", { class: "card" }, h("h2", { class: "card-title" }, icon("star", 22), "Proponowane zadania"),
    h("div", { class: "stack" },
      open ? h("div", { class: "quest featured" }, h("div", { class: "icon-box" }, icon(KIND_ICON[open.kind] || "lesson", 36)),
        h("div", {}, h("h3", {}, "Niedokończona sesja"), h("p", {}, `${KIND_PL[open.kind] || "Sesja"} — wróć do miejsca, w którym przerwano.`)),
        btn("Wznów", () => resume(open), "primary", "play")) : null,
      d.suggested_lesson ? h("div", { class: `quest${open ? "" : " featured"}` }, h("div", { class: "icon-box" }, icon("lesson", 36)),
        h("div", {}, h("span", { class: "chip gold" }, "Lekcja"), h("h3", {}, lessonName(d.suggested_lesson.skill_id)), h("p", {}, d.suggested_lesson.reason)),
        btn("Zacznij", () => startSession("lesson", { text_mode: defaultTextMode() }), "primary", "play")) : null,
      h("div", { class: "quest" }, h("div", { class: "icon-box" }, icon("review", 36)),
        h("div", {}, h("span", { class: "chip sky" }, "Powtórki"), h("h3", {}, d.due_reviews ? `${d.due_reviews} do powtórki dziś` : "Brak zaległych powtórek"),
          h("p", {}, "Sprawdzają, czy pamiętasz — na nowych przykładach.")),
        btn("Powtórz", () => startSession("review", { text_mode: defaultTextMode() }), d.due_reviews ? "primary" : "", "review"))));

  const quick = topics.length ? card(null, h("h2", { class: "card-title" }, icon("chat", 22), "Porozmawiajmy o…", h("a", { class: "more", href: "#/chat" }, "Więcej tematów")),
    h("div", { class: "topic-grid" }, topics.slice(0, 3).map((t) => topicCard(t, () => startSession("chat", { topic: t.id, text_mode: defaultTextMode() }))))) : null;

  const unearned = ac.items.filter((i) => !i.earned).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  const challenges = card(null, h("h2", { class: "card-title" }, icon("flame", 22), "Aktualne wyzwania", h("a", { class: "more", href: "#/achievements" }, "Wszystkie")),
    unearned.length ? h("ul", { class: "mini-list" }, unearned.map((i) => h("li", { class: "challenge" }, badgeArt(i.category, tierOf(ac.items, i), false, 40),
      h("div", {}, h("div", { class: "t" }, i.name), h("div", { class: "s" }, `${i.description} · ${Math.min(i.progress, i.target)}/${i.target}`), bar(i.progress, i.target, i.name, "gold"))))) : note("Wszystkie wyzwania zdobyte."));

  const who = S.profiles.find((p) => p.id === S.pid);
  const t = hs.totals;
  const profile = h("section", { class: "card profile-card" },
    h("div", { class: "who" }, h("div", { class: "avatar", "aria-hidden": "true" }, (who?.name || "?").slice(0, 1).toUpperCase()),
      h("div", {}, h("strong", {}, who?.name || ""), h("span", { class: "muted" }, d.placement_done ? "Poziom wstępnie sprawdzony" : "Poziom jeszcze nie sprawdzony"))),
    h("div", { class: "stat-grid" }, stat("Seria dni", d.streak || 0), stat("Odznaki", `${ac.earned}/${ac.total}`),
      stat("Lekcje", t.lessons_completed), stat("Czas nauki", fmtMin(t.study_seconds))),
    profileBox());

  const earned = ac.items.filter((i) => i.earned).sort((a, b) => String(b.earned_at).localeCompare(String(a.earned_at))).slice(0, 3);
  const recentBadges = card(null, h("h2", { class: "card-title" }, icon("trophy", 22), "Ostatnie osiągnięcia"),
    earned.length ? h("ul", { class: "mini-list" }, earned.map((i) => h("li", {}, badgeArt(i.category, tierOf(ac.items, i), true, 36),
      h("div", {}, h("div", { class: "t" }, i.name), h("div", { class: "s" }, fmtDay(i.earned_at)))))) : note("Pierwsza odznaka czeka po pierwszej sesji.", "muted"));

  const recent = card(null, h("h2", { class: "card-title" }, icon("progress", 22), "Ostatnie postępy", h("a", { class: "more", href: "#/progress" }, "Szczegóły")),
    hs.sessions.length ? h("ul", { class: "mini-list" }, hs.sessions.slice(0, 4).map((s) => h("li", {}, icon(KIND_ICON[s.kind] || "chat", 24),
      h("div", {}, h("div", { class: "t" }, KIND_PL[s.kind] || s.title), h("div", { class: "s" }, `${fmtDate(s.started_at)} · ${fmtMin(s.seconds)}`)),
      h("span", { class: "s" }, s.attempts ? `${s.attempts_correct}/${s.attempts}` : `${s.user_turns} wyp.`)))) : note("Brak sesji — zacznij od rozmowy albo lekcji.", "muted"));

  main.append(hero, h("div", { class: "grid-2" }, h("div", { class: "stack" }, quests, quick, challenges), h("div", { class: "stack" }, profile, recentBadges, recent)));
}

function resume(open) {
  const map = { chat: "chat", lesson: "lesson", placement: "placement", review: "review", exam: "exam" };
  if (open.kind === "chat") return startSession("chat", { topic: (open.plan && open.plan.topic && open.plan.topic.id) || "fd.cooking", text_mode: defaultTextMode() });
  if (open.kind === "exam") return (location.hash = "#/exam");
  startSession(map[open.kind] || "lesson", { text_mode: defaultTextMode() });
}

function modeRow() {
  const cb = h("input", { type: "checkbox", id: "textmode", checked: defaultTextMode(), disabled: !voiceAvailable() });
  return h("label", { class: "check" }, cb, voiceAvailable() ? "Tryb tekstowy (bez mikrofonu i głosu)" : "Tryb tekstowy — głos niedostępny na tym komputerze");
}
const textMode = () => { const cb = document.getElementById("textmode"); return cb ? cb.checked : defaultTextMode(); };

// ---------- Quick Chat ----------
const TOPIC_TONE = { food: "gold", tech: "sky", work: "violet", hobbies: "mint", travel: "sky", home: "gold", people: "violet", health: "red" };
function topicCard(t, onclick) {
  return h("button", { class: "topic", type: "button", onclick }, chip(t.category_pl, TOPIC_TONE[t.category] || ""), h("strong", {}, t.pl), h("em", { lang: "en" }, t.q));
}

async function screenChat(main) {
  let seed = null;
  const list = h("div", { class: "topic-grid two", "aria-live": "polite" });
  const custom = h("input", { type: "text", maxlength: 80, placeholder: "np. my first job, football, cats…", "aria-label": "Własny temat" });
  const minutes = seg("Czas rozmowy", [["", "bez limitu"], ["5", "5"], ["10", "10"], ["15", "15"], ["20", "20"], ["30", "30"]], "");
  const corrNow = S.settings?.values?.correction || "summary";
  const corr = seg("Intensywność poprawek", [["summary", "na końcu"], ["periodic", "co jakiś czas"], ["intensive", "na bieżąco"]], corrNow);
  const go = (args) => startSession("chat", { ...args, minutes: minutes.value || null, correction: corr.value, text_mode: textMode() });
  const draw = async () => {
    const ts = await q("/api/topics", seed === null ? "" : `&seed=${seed}`);
    list.replaceChildren(...ts.map((t) => topicCard(t, () => go({ topic: t.id }))));
  };
  await draw();
  const hist = await q("/api/chats").catch(() => []);
  const customGo = () => (custom.value.trim() ? go({ custom: custom.value.trim() }) : toast("Wpisz temat."));
  custom.addEventListener("keydown", (e) => { if (e.key === "Enter") customGo(); });
  main.append(
    pageHead("Rozmowa z nauczycielem", "Quick Chat", "Swobodna rozmowa po angielsku. Kliknij temat, aby zacząć od razu."),
    h("div", { class: "chat-setup" },
      h("div", { class: "stack" },
        h("section", { class: "card" }, h("div", { class: "greet" }, mascot("idle", 84),
          h("p", { class: "speech", lang: "en" }, "Hi! Pick a topic and we'll just talk. I'll help with mistakes along the way.")),
        ),
        card(null, h("h2", { class: "card-title" }, icon("chat", 22), "Tematy", h("span", { class: "more" }, btn("Wylosuj inne", () => { seed = Math.floor(Math.random() * 1e9); draw(); }, "sm", "dice"))),
          list),
        card("Własny temat", h("div", { class: "custom-topic" }, custom, btn("Rozmawiaj o tym", customGo, "primary", "play")),
          note("Temat zakończony znakiem zapytania staje się pierwszym pytaniem nauczyciela.", "muted"))),
      h("div", { class: "stack" },
        card("Ustawienia rozmowy", h("div", { class: "opts" },
          h("div", { class: "opt" }, h("span", {}, "Czas (minuty)"), minutes),
          h("div", { class: "opt" }, h("span", {}, "Poprawki"), corr),
          h("div", { class: "opt" }, h("span", {}, "Tryb"), modeRow())),
        note("Quick Chat nie nadaje statusu opanowania. Poprawki to sugestie modelu i mogą być błędne.", "muted")),
        hist.length ? card("Ostatnie rozmowy", h("ul", { class: "mini-list" }, hist.slice(0, 6).map((c) => h("li", {}, icon("chat", 20),
          h("div", {}, h("div", { class: "t" }, (c.topics || []).join(" → ") || "—"), h("div", { class: "s" }, `${fmtDate(c.started_at)} · ${fmtMin(c.seconds_active)}`)),
          h("span", { class: "s" }, `${c.user_turns ?? 0} wyp.`))))) : null)));
}

// ---------- Lekcje: mapa misji ----------
const CHAPTER = { A1: "Pierwsze kroki", A2: "Codzienne sprawy", B1: "Samodzielność", B2: "Swoboda", C1: "Biegłość", C2: "Mistrzostwo" };
const AREA_ICON = { grammar: "lesson", vocabulary: "star", speaking: "mic", writing: "exam", reading: "lesson", listening: "chat" };
const STATUS = {
  mastered: ["Opanowana", "gold"], working: ["W toku", "mint"], struggling: ["Do poprawy", "red"], too_few: ["Rozpoczęta", "sky"], new: ["Nowa", ""],
};

async function screenLesson(main) {
  const [d, p] = await Promise.all([q("/api/lessons"), q("/api/progress")]);
  const status = {};
  for (const k of ["mastered", "working", "struggling", "too_few"]) for (const r of p.skills[k]) status[r.skill] = { k, r };
  const sug = d.suggestion;
  const by = {};
  d.catalog.forEach((c) => (by[c.cefr] = by[c.cefr] || []).push(c));
  const sugName = sug && (d.catalog.find((c) => c.skill_id === sug.skill_id) || {}).can_do_pl;
  main.append(
    pageHead("Mapa misji", "Lekcje", `${d.catalog.length} misji z kompletem materiałów (wyjaśnienie i zadania). Kliknij misję, aby ją zacząć.`, modeRow()),
    sug ? h("section", { class: "quest featured" }, h("div", { class: "icon-box" }, icon("star", 36)),
      h("div", {}, h("span", { class: "chip gold" }, "Polecana misja"), h("h3", {}, sugName || sug.skill_id), h("p", {}, sug.reason),
        sug.provisional ? h("p", { class: "muted" }, "To propozycja startowa, nie wynik diagnozy.") : null),
      btn("Zacznij misję", () => startSession("lesson", { text_mode: textMode() }), "primary lg", "play")) : note("Brak lekcji z gotowymi materiałami."),
    h("div", { class: "legend", "aria-label": "Legenda" }, Object.values(STATUS).map(([l, c]) => chip(l, c))),
    h("div", { class: "chapters" }, Object.entries(by).map(([cefr, items], i) => h("section", { class: "chapter", "aria-labelledby": `ch-${cefr}` },
      h("div", { class: "chapter-head" }, h("div", { class: "lvl" }, cefr),
        h("div", {}, h("h2", { id: `ch-${cefr}` }, `Rozdział ${i + 1}: ${CHAPTER[cefr] || cefr}`),
          h("p", {}, `${items.filter((c) => status[c.skill_id]).length} z ${items.length} misji rozpoczętych`))),
      h("div", { class: "missions" }, items.map((c) => {
        const st = status[c.skill_id];
        const [label, tone] = STATUS[st ? st.k : "new"];
        return h("button", { type: "button", class: `mission${sug && sug.skill_id === c.skill_id ? " suggested" : ""}`, "data-status": st ? st.k : "new",
          onclick: () => startSession("lesson", { skill: c.skill_id, text_mode: textMode() }) },
          h("div", { class: "icon-box" }, icon(st && st.k === "mastered" ? "trophy" : AREA_ICON[c.area] || "lesson", 30)),
          h("strong", {}, c.can_do_pl),
          h("span", { class: "meta" }, chip(label, tone), h("span", { class: "muted" }, areaPl(c.area))),
          st ? bar(st.r.correct, st.r.attempts, `Poprawnie ${st.r.correct} z ${st.r.attempts}`) : null);
      }))))),
    note("Materiały nie są jeszcze sprawdzone przez człowieka. Status „Opanowana” nadaje wyłącznie silnik oceny.", "muted"));
}

async function screenReview(main) {
  const home = await q("/api/home");
  main.append(pageHead("Utrwalanie", "Powtórki", "Sprawdzają utrwalenie na nowych przykładach. Nie nadają opanowania. Limit: 20 dziennie."),
    h("section", { class: "quest featured" }, h("div", { class: "icon-box" }, icon("review", 36)),
      h("div", {}, h("h3", {}, home.due_reviews ? `Do powtórki dziś: ${home.due_reviews}` : "Dziś nie ma zaległych powtórek"), h("p", {}, "Harmonogram FSRS wybiera, co warto sprawdzić."), modeRow()),
      btn("Zacznij powtórki", () => startSession("review", { text_mode: textMode() }), home.due_reviews ? "primary lg" : "lg", "play")));
}

async function screenPlacement(main) {
  const d = await q("/api/placement");
  main.append(pageHead("Dobrowolnie", "Określ poziom", d.notice),
    card("Jak to działa", note("Możesz przerwać w dowolnym momencie (przycisk Zakończ) i wznowić później. Ponowne sprawdzenie nie kasuje historii nauki. Niepewne rozpoznanie mowy nie obniża wyniku."),
      table(["Obszar", "Pytania w banku"], d.areas.map((a) => [areaPl(a.area), a.items])),
      h("div", { class: "row" }, modeRow(), btn(d.results.length ? "Sprawdź ponownie" : "Zacznij", () => startSession("placement", { text_mode: textMode() }), "primary", "level"))),
    card("Wyniki (szacunek wstępny)", d.results.length ? table(["Data", "Obszar", "Wynik", "Uwagi"],
      d.results.map((r) => [fmtDate(r.measured_at), areaPl(r.area), `${r.label || "—"} (${r.status})`, r.notice || ""])) : note("Jeszcze nie sprawdzano poziomu.")));
}
const areaPl = (a) => ({ grammar: "gramatyka", vocabulary: "słownictwo", speaking: "mówienie", reading: "czytanie", listening: "słuchanie", writing: "pisanie" }[a] || a);

const REL = {
  "potwierdzony ćwiczeniami": ["ok", "Potwierdzony ćwiczeniami"],
  "sugestia modelu": ["warn", "Sugestia modelu (niepotwierdzona)"],
  "niepewna transkrypcja STT": ["stt", "Możliwy błąd rozpoznawania mowy"],
  "za mało danych": ["none", "Za mało danych"],
};
async function screenWeak(main) {
  const d = await q("/api/weakspots");
  const head = pageHead("Dziennik błędów", "Słabe strony", "Każdy wpis ma etykietę wiarygodności. Sugestia modelu nie jest potwierdzonym błędem.");
  if (!d.has_data) {
    main.append(head, card(null, note("Jeszcze nic tu nie ma. Wpisy pojawią się po rozmowach, lekcjach i powtórkach."), note(d.stt_uncertain.note, "muted")));
    return;
  }
  main.append(head,
    d.errors.length ? card(null, note("Trend pokazujemy dopiero przy co najmniej 5 wypowiedziach w obu okresach.", "muted"), h("div", { class: "weak-list" }, d.errors.map((e, i) => {
      const [cls, label] = REL[e.reliability] || ["none", e.reliability];
      const t = e.trend || {};
      return h("article", { class: "weak" },
        h("header", {}, h("strong", {}, `${i + 1}. ${e.category}`), h("span", { class: `badge ${cls}` }, label)),
        h("p", {}, `Wystąpienia: ${e.count} · pierwszy raz ${fmtDate(e.first_seen)} · ostatnio ${fmtDate(e.last_seen)}`),
        e.example && cls !== "stt" ? h("p", { class: "example", lang: "en" }, h("span", { class: "bad" }, e.example), e.correction ? [" → ", h("span", { class: "good" }, e.correction)] : null) : null,
        h("p", { class: "muted" }, `Trend (14 dni): ${t.direction || "za mało danych"} — ${t.last_14d ?? 0} obserwacji / ${t.utterances_last_14d ?? 0} wypowiedzi (poprzednio ${t.previous_14d ?? 0} / ${t.utterances_previous_14d ?? 0})`),
        e.skills.length ? h("div", {}, btn("Ćwicz to", () => startSession("drill", { target: String(i + 1), text_mode: defaultTextMode() }), "primary", "play")) : note("Brak materiałów do ćwiczeń dla tej kategorii.", "muted"));
    }))) : null,
    d.weak_skills.length ? card("Umiejętności z wynikiem poniżej połowy", table(["Umiejętność", "Poprawnie", ""],
      d.weak_skills.map((w) => [w.skill, `${w.correct}/${w.attempts}`, btn("Ćwicz", () => startSession("drill", { target: w.skill, text_mode: defaultTextMode() }), "sm")]))) : null,
    d.vocabulary.length ? card("Słowa do utrwalenia", table(["Słowo", "Pomyłki"], d.vocabulary.map((w) => [w.term, w.misses]))) : null,
    card("Niepewne rozpoznanie mowy", h("p", {}, `${d.stt_uncertain.count} — ${d.stt_uncertain.note}`)),
    d.due_reviews.length ? card("Do powtórki", h("p", {}, d.due_reviews.join(", ")), btn("Zacznij powtórki", () => { location.hash = "#/review"; })) : null);
}

async function screenExam(main) {
  const paths = await q("/api/exams");
  main.append(pageHead("Ścieżki egzaminacyjne", "Egzaminy", "Ćwiczenia w formacie egzaminu. Wynik ćwiczeń nie jest prognozą wyniku egzaminu."));
  for (const p of paths) {
    const r = p.readiness;
    main.append(card(p.name,
      note(p.disclaimer, "muted"),
      table(["Część", "Materiały", "Wynik ćwiczeń", "Stan"], r.sections.map((s) => {
        const cov = p.coverage.find((c) => c.section === s.section) || {};
        return [s.name, cov.status === "ok" ? `${cov.items} zadań` : (cov.note || "brak"), s.scored ? `${s.correct}/${s.scored}` : "—", s.label];
      })),
      h("ul", { class: "limits" }, [...new Set(r.limits || [])].filter((l) => l !== p.disclaimer).map((l) => h("li", {}, l))),
      p.speaking_topics.length ? h("div", {}, h("h3", { class: "card-title" }, "Mówienie (w Quick Chat)"), h("div", { class: "row" },
        p.speaking_topics.map((t) => btn(t.pl, () => startSession("chat", { custom: t.q.slice(0, 80), text_mode: defaultTextMode() }), "sm", "chat")))) : null,
      h("div", { class: "row" }, modeRow(), btn("Ćwicz tę ścieżkę", () => startSession("exam", { path: p.id, text_mode: textMode() }), "primary", "exam"))));
  }
  main.append(note("Matura i Cambridge: przygotowane w architekturze, bez materiałów — nie są jeszcze dostępne.", "muted"));
}

async function screenProgress(main) {
  const [p, hs, ac] = await Promise.all([q("/api/progress"), q("/api/history"), q("/api/achievements")]);
  const t = hs.totals;
  const small = (n) => (n < 5 ? " (mała próba)" : "");
  main.append(
    pageHead("Dziennik nauki", "Postępy", "Wszystko pochodzi z bazy na tym komputerze. Czas nauki to przybliżenie z odstępów między zapisami."),
    card(null, h("div", { class: "stats" },
      stat("Czas nauki", fmtMin(t.study_seconds)), stat("Sesje", t.sessions), stat("Ukończone lekcje", t.lessons_completed),
      stat("Powtórki", t.reviews_done), stat("Twoje wypowiedzi", t.user_turns), stat("Osiągnięcia", `${ac.earned}/${ac.total}`))),
    card("Poziom (dobrowolne sprawdzenie)", table(["Obszar", "Stan", "Wynik", "Data"],
      p.competence.map((c) => [areaPl(c.area), c.state, c.label || "—", fmtDate(c.measured_at)]))),
    card("Umiejętności", ...[["mastered", "Opanowane (potwierdzone przez silnik)"], ["working", "W toku"], ["struggling", "Wymagają pracy"], ["too_few", "Za mało prób"]].map(([k, label]) =>
      h("div", {}, h("h3", { class: "card-title" }, `${label}: ${p.skills[k].length}`), p.skills[k].length ? table(["Umiejętność", "Poprawnie", "Nowe zadania"],
        p.skills[k].map((r) => [r.skill, `${r.correct}/${r.attempts}${small(r.attempts)}`, r.new_items])) : null))),
    p.changes.length ? card("Zmiany między sesjami", table(["Umiejętność", "Poprzednio", "Ostatnio"],
      p.changes.map((c) => [c.skill, `${c.previous[0]}/${c.previous[1]}`, `${c.latest[0]}/${c.latest[1]}${small(c.latest[1])}`]))) : null,
    card("Historia sesji", hs.sessions.length ? table(["Data", "Rodzaj", "Status", "Czas", "Wypowiedzi", "Zadania"],
      hs.sessions.map((s) => [fmtDate(s.started_at), KIND_PL[s.kind] || s.kind, s.status, fmtMin(s.seconds), s.user_turns, s.attempts ? `${s.attempts_correct}/${s.attempts}` : "—"])) : note("Brak sesji.")));
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
            chip(TIER_PL[tier], i.earned ? "gold" : ""),
            i.earned ? null : h("span", { class: "lockmark", "aria-hidden": "true" }, icon("lock", 20)),
            badgeArt(i.category, tier, i.earned, 80),
            h("strong", {}, i.name), h("span", { class: "desc" }, i.description),
            i.earned ? h("span", { class: "when" }, `Zdobyte ${fmtDay(i.earned_at)}`)
              : h("div", { class: "prog" }, bar(i.progress, i.target, `${i.name}: ${Math.min(i.progress, i.target)} z ${i.target}`, "gold"), `${Math.min(i.progress, i.target)} / ${i.target}`));
        })));
    }).filter(Boolean));
  };
  const near = d.items.filter((i) => !i.earned && i.progress > 0).sort((a, b) => b.progress / b.target - a.progress / a.target).slice(0, 3);
  main.append(
    h("section", { class: "trophy-hero" }, icon("trophy", 84),
      h("div", {}, h("span", { class: "eyebrow" }, "Sala trofeów"),
        h("h1", {}, h("span", { class: "sr-only" }, "Osiągnięcia"), pxText("Osiągnięcia", 5)),
        h("p", { class: "muted" }, d.note || "Odznaki nagradzają regularną pracę. Nie oznaczają opanowania języka."),
        bar(d.earned, d.total, `Zdobyte ${d.earned} z ${d.total}`, "gold")),
      h("div", { class: "counter" }, h("strong", {}, `${d.earned}/${d.total}`), h("span", {}, "zdobytych odznak"))),
    near.length ? card(null, h("h2", { class: "card-title" }, icon("flame", 22), "Najbliżej zdobycia"),
      h("div", { class: "near" }, near.map((i) => h("div", { class: "badge-row" }, badgeArt(i.category, tierOf(d.items, i), false, 48),
        h("div", {}, h("strong", {}, i.name), h("div", { class: "muted" }, i.description), bar(i.progress, i.target, i.name, "gold")))))) : null,
    h("div", { class: "row" }, seg("Filtr odznak", [["all", "Wszystkie"], ["earned", "Zdobyte"], ["locked", "Do zdobycia"]], filter, (v) => { filter = v; draw(); })),
    shelves);
  draw();
}

// ---------- Ustawienia ----------
const SET_LABELS = {
  chat_model: "Model rozmowy", tts_voice: "Głos nauczyciela", speed: "Tempo mowy", correction: "Poprawki",
  session_minutes: "Dzienny czas nauki (min)", io_mode: "Tryb domyślny", mic_mode: "Mikrofon",
  input_device: "Mikrofon (urządzenie)", output_device: "Głośnik (urządzenie)", stt_model: "Rozpoznawanie mowy",
  allow_unreviewed: "Używaj materiałów niesprawdzonych przez człowieka", conversation_mode: "Domyślna aktywność", target_lang: "Język nauki",
};
const CHOICE_LABELS = { summary: "podsumowanie", periodic: "co jakiś czas", intensive: "intensywnie", ptt: "naciśnij, aby mówić", auto: "automatyczny", voice: "głosowy", text: "tekstowy", quick_chat: "Quick Chat", lesson: "lekcja", en: "angielski" };
async function screenSettings(main) {
  const d = S.settings = await q("/api/settings");
  const st = S.system;
  const form = h("form", { class: "settings", onsubmit: (e) => e.preventDefault() });
  const fields = {};
  for (const [key, spec] of Object.entries(d.schema)) {
    if (key === "stt_model") continue;      // inne modele Whisper nie są zweryfikowane w aplikacji
    const val = d.values[key];
    let input;
    if (key === "tts_voice" && st && st.voices.length) input = h("select", {}, st.voices.map((v) => h("option", { value: v, selected: v === val }, v)));
    else if ((key === "input_device" || key === "output_device")) {
      if (!st || st.audio_error) continue;
      input = h("select", {}, h("option", { value: "default", selected: val === "default" }, "systemowe"), st.devices.map((v) => h("option", { value: v, selected: v === val }, v)));
    } else if (spec.type === "choice") input = h("select", {}, spec.choices.map((c) => h("option", { value: c, selected: String(c) === String(val) },
      key === "chat_model" ? `${c}${st && st.models.includes(c) ? "" : " (nie pobrany)"}` : (CHOICE_LABELS[c] || c))));
    else if (spec.type === "float") input = h("input", { type: "number", min: spec.min, max: spec.max, step: 0.05, value: val });
    else if (spec.type === "bool") input = h("input", { type: "checkbox", checked: !!val });
    else continue;
    fields[key] = input;
    form.append(h("label", { class: "field" }, h("span", {}, SET_LABELS[key] || key), input));
  }
  const save = async () => {
    const changes = {};
    for (const [k, el] of Object.entries(fields)) changes[k] = el.type === "checkbox" ? el.checked : el.value;
    try { S.settings.values = await api("/api/settings", { pid: S.pid, changes }); toast("Zapisano ustawienia."); setStatus(); }
    catch (e) { toast(e.message); }
  };
  main.append(pageHead("Profil ucznia", "Ustawienia", "Zmiany dotyczą tylko wybranego profilu."),
    card(null, form, h("div", { class: "row" }, btn("Zapisz", save, "primary", "check")),
      note("Model oceny zostaje bez zmian (Qwen3 8B): jego zmiana wymaga kontroli jakości. Model rozmowy musi być pobrany w Ollamie.", "muted")),
    card("Ten komputer", table(["Element", "Stan"], st ? [
      ["Ollama", st.ollama ? "działa" : "nie odpowiada"], ["Pobrane modele", st.models.join(", ") || "—"],
      ["Model oceny", st.roles.evaluation || "—"], ["Głos (Kokoro)", st.kokoro ? `gotowy, ${st.voices.length} głosów` : "brak plików modelu"],
      ["Audio", st.audio_error ? `niedostępne: ${st.audio_error}` : st.devices.join("; ")]] : [])));
}

// ---------- sesja ----------
const KIND_TITLE = { chat: "Quick Chat", lesson: "Lekcja", placement: "Określ poziom", review: "Powtórki", drill: "Ćwiczenia słabej strony", exam: "Ćwiczenia egzaminacyjne" };
const STATE_PL = { listening: "Słucham…", thinking: "Myślę…", speaking: "Mówię…", turn: "Twoja kolej", idle: "Sesja zakończona", connecting: "Łączę…" };

function newSession(kind, text) {
  return { kind, phase: null, running: true, text, log: [], task: null, heard: null, feedback: null, goal: null, recording: false, waiting: true, speaking: false, topic: null, started: Date.now() };
}

async function startSession(kind, args) {
  try {
    await api("/api/session/start", { pid: S.pid, kind, args });
    S.seq = 0;
    S.session = newSession(kind, !!args.text_mode);
    location.hash = "#/session";
  } catch (e) { toast(e.message); }
}

function mascotState(s) {
  if (!s.running) return "idle";
  if (s.recording) return "listening";
  if (s.speaking && !s.text) return "speaking";
  if (s.waiting) return "thinking";
  return "turn";
}

function screenSession(main) {
  const s = S.session;
  if (!s) { main.append(card("Sesja", note("Brak aktywnej sesji."), btn("Na start", () => { location.hash = "#/home"; }))); return; }
  const log = h("div", { class: "log", id: "log", "aria-live": "polite", "aria-label": "Przebieg rozmowy" });
  const input = h("input", { type: "text", id: "say", maxlength: 500, lang: "en", placeholder: s.text ? "Napisz odpowiedź po angielsku…" : "Mów przyciskiem mikrofonu albo napisz…", "aria-label": "Twoja odpowiedź" });
  const send = async (text) => {
    try { await api("/api/session/send", { text }); if (text) { s.waiting = true; drawSide(); } } catch (e) { toast(e.message); }
  };
  const submit = () => {
    const t = input.value.trim(); if (!t) return; input.value = "";
    if (s.kind !== "chat" && s.phase !== "chat") drawEvent({ kind: "you", text: t, seq: -1 }, true);   // ćwiczenia: silnik nie powtarza odpowiedzi
    send(t);
  };
  S.answer = (t) => { input.value = t; submit(); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const mic = s.text ? null : h("button", { type: "button", class: "mic-btn", id: "micbtn", "aria-label": "Mów", onclick: () => send("") }, icon("mic", 30));
  const quick = s.kind === "chat"
    ? [["Powtórz", "Could you repeat that, please?"], ["Wyjaśnij prościej", "Could you explain that in simpler words?"], ["Zmień temat", "Can we change the topic?"]]
    : ["exam", "placement"].includes(s.kind) ? [["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?"]]
      : [["Podpowiedź", "Could you explain, please?"], ["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?"]];
  main.append(h("div", { class: "session" },
    h("section", { class: "convo", "aria-label": "Rozmowa" },
      h("div", { class: "convo-head" }, icon(KIND_ICON[s.kind] || "chat", 28), h("h1", {}, KIND_TITLE[s.kind] || s.kind),
        h("span", { class: "state state-label", id: "sstate", "data-state": "connecting" }, STATE_PL.connecting)),
      log,
      h("div", { class: "composer" }, mic, input, btn("Wyślij", submit, "primary")),
      h("div", { class: "quickbar" }, quick.map(([l, t]) => btn(l, () => send(t), "sm")), h("span", { class: "muted" }), btn("Zakończ", () => api("/api/session/stop", {}).catch((e) => toast(e.message)), "danger sm"))),
    h("aside", { class: "side", id: "side", "aria-label": "Stan sesji" })));
  s.log.forEach((ev) => drawEvent(ev, false));
  drawSide();
  input.focus();
  pollSession();
}

function drawEvent(ev, store = true) {
  const s = S.session;
  if (store) s.log.push(ev);
  const log = document.getElementById("log");
  const k = ev.kind;
  if (store) {
    if (k === "task") { s.task = ev; s.heard = null; s.feedback = null; }
    if (k === "heard") s.heard = ev.text;
    if (k === "feedback") { s.feedback = ev.text; s.hint = null; }
    if (k === "hint") s.hint = ev.text;
    if (k === "task") s.hint = null;
    if (k === "goal") s.goal = ev.text.split("\n")[0].replace(/^Cel lekcji:\s*\S+\s*\((\w+)\)\s*—\s*/, "$1 · ");
    if (k === "recording") { s.recording = true; s.speaking = false; }
    if (k === "info" && ev.text.trim().startsWith("Teraz krótka rozmowa")) s.phase = "chat";
    if (["you", "tutor", "prompt", "end", "heard"].includes(k)) s.recording = false;
    if (["you", "heard"].includes(k)) s.waiting = true;
    if (["tutor", "task", "feedback", "hint", "prompt", "error", "end", "goal"].includes(k)) s.waiting = false;
    if (k === "tutor") s.speaking = true;
    if (["prompt", "listening", "end", "you"].includes(k)) s.speaking = false;
    if (k === "info" && ev.text.startsWith("Quick Chat — temat:")) s.topic = ev.text.replace("Quick Chat — temat:", "").split("(")[0].trim().replace(/\.$/, "");
    if (k === "notice" && ev.text.startsWith("nowy temat:")) s.topic = ev.text.replace("nowy temat:", "").trim();
  }
  if (!log) return;
  if (["prompt", "start", "metric", "listening"].includes(k)) return;
  if (k === "info" && /^(\[Enter\]|Profil:)/.test(ev.text)) return;
  const last = log.lastElementChild;
  if (k === "tutor" && last && last.classList.contains("tutor") && last.dataset.seq == ev.seq - 1) {   // jedna wypowiedź, kilka zdań
    last.querySelector(".bubble").textContent += " " + ev.text; last.dataset.seq = ev.seq; log.scrollTop = log.scrollHeight; return;
  }
  let el;
  if (k === "tutor") el = h("div", { class: "msg tutor" }, h("div", { class: "avatar-s", "aria-hidden": "true" }, mascotHead(28)), h("div", {}, h("b", {}, "Emma"), h("p", { class: "bubble", lang: "en" }, ev.text)));
  else if (k === "you") el = h("div", { class: "msg you" }, h("b", {}, "Ty"), h("p", { lang: "en" }, ev.text));
  else if (k === "task") el = h("div", { class: "msg task" }, h("b", {}, `Zadanie ${ev.index}/${ev.total}${ev.tag ? " · " + ev.tag : ""}`), h("pre", {}, ev.text));
  else if (k === "goal") el = h("div", { class: "msg goal" }, h("b", {}, "Cel misji"), rich(ev.text));
  else if (k === "feedback") el = h("div", { class: `msg feedback${ev.text.startsWith("✓") ? " ok" : ""}` }, h("pre", {}, ev.text.trim()));
  else if (k === "hint") el = h("div", { class: "msg feedback" }, h("b", {}, "Wskazówka"), h("p", {}, ev.text));
  else if (k === "heard") el = h("div", { class: "msg heard" }, `Rozpoznano: „${ev.text}”`);
  else if (k === "error") el = h("div", { class: "msg error", role: "alert" }, h("b", {}, "Błąd"), h("p", {}, ev.text));
  else if (k === "end") el = h("div", { class: "msg sys" }, ev.code ? "Sesja zakończona z błędem." : "Sesja zamknięta. Wyniki zapisano; przerwaną lekcję, powtórki lub sprawdzenie poziomu możesz wznowić tym samym przyciskiem.");
  else if (k === "recording") el = h("div", { class: "msg sys rec" }, "● Nagrywam — kliknij mikrofon jeszcze raz, gdy skończysz.");
  else el = h("div", { class: `msg ${k}` }, h("pre", {}, ev.text.trim()));
  el.dataset.seq = ev.seq;
  log.append(el);
  log.scrollTop = log.scrollHeight;
}

function drawSide() {
  const s = S.session, side = document.getElementById("side");
  if (!side) return;
  document.querySelectorAll(".composer input, .composer button, .quickbar button").forEach((b) => { b.disabled = !s.running; });
  const state = mascotState(s);
  const mic = document.getElementById("micbtn");
  if (mic) { mic.classList.toggle("on", s.recording); mic.setAttribute("aria-label", s.recording ? "Stop — zakończ nagrywanie" : "Mów"); mic.disabled = !s.running; }
  const st = document.getElementById("sstate");
  if (st) { st.dataset.state = state; st.textContent = STATE_PL[state]; }
  const parts = [];
  const tutor = side.querySelector(".tutor-card") || h("section", { class: "tutor-card" }, mascot(state, 120), h("span", { class: "state-label" }));
  tutor.querySelector(".mascot").dataset.state = state;
  const lab = tutor.querySelector(".state-label");
  lab.dataset.state = state; lab.textContent = STATE_PL[state];
  parts.push(tutor);
  if (s.text && s.running) parts.push(note("Tryb tekstowy: odpowiadaj, pisząc po angielsku.", "muted"));
  else if (s.running) parts.push(note("Kliknij mikrofon, powiedz odpowiedź, kliknij jeszcze raz. Możesz też pisać.", "muted"));
  if (s.kind === "chat") {
    const min = Math.floor((Date.now() - s.started) / 60000);
    parts.push(h("section", { class: "card" }, h("h3", {}, "Temat"), h("p", { class: "big" }, s.topic || "…"), h("p", { class: "muted" }, `Czas: ${min} min`),
      note("Poprawki pojawiają się w odpowiedziach nauczyciela; podsumowanie — na końcu.", "muted")));
  } else {
    if (s.goal) parts.push(h("section", { class: "card" }, h("h3", {}, "Cel misji"), h("p", {}, s.goal)));
    if (s.phase === "chat") parts.push(h("section", { class: "card" }, h("h3", {}, "Rozmowa po ćwiczeniach"), note("Użyj tego, co ćwiczysz. „Zakończ” zamyka lekcję i pokazuje podsumowanie poprawek.", "muted")));
    else if (s.task) {
      const opts = [...s.task.text.matchAll(/^\s+\d+\.\s+(.+)$/gm)].map((m) => m[1].trim());
      const stem = s.task.text.replace(/\n\s+\d+\.\s+.+/g, "");
      parts.push(h("section", { class: "card" }, h("h3", {}, `Zadanie ${s.task.index} z ${s.task.total}`),
        h("div", { class: "steps", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": s.task.total, "aria-valuenow": s.task.index - 1, "aria-label": "Postęp misji" },
          Array.from({ length: s.task.total }, (_, i) => h("i", { class: i < s.task.index - 1 ? "done" : i === s.task.index - 1 ? "now" : "" }))),
        h("pre", { class: "task-text", lang: "en" }, stem),
        opts.length && s.running ? h("div", { class: "options" }, opts.map((o) => btn(o, () => S.answer(o)))) : null));
    }
    if (s.heard) parts.push(h("section", { class: "card" }, h("h3", {}, "Rozpoznano"), h("p", { lang: "en" }, s.heard)));
    if (s.hint) parts.push(h("section", { class: "card" }, h("h3", {}, "Wskazówka"), h("p", { class: "feedback-box" }, s.hint)));
    if (s.feedback) {
      const cls = s.feedback.startsWith("✓") ? "good" : /^(✗|Poprawna odpowiedź)/.test(s.feedback) ? "bad" : "";
      parts.push(h("section", { class: "card" }, h("h3", {}, "Ocena"), h("p", { class: `feedback-box ${cls}` }, s.feedback)));
    }
    if (parts.length === 2 || (parts.length === 3 && !s.goal && !s.task)) parts.push(note("Za chwilę pojawi się pierwsze zadanie.", "muted"));
  }
  if (!s.running) parts.push(h("div", { class: "row" }, btn("Zobacz postępy", () => { location.hash = "#/progress"; }, "primary"), btn("Na start", () => { location.hash = "#/home"; })));
  side.replaceChildren(...parts.filter(Boolean));
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
const ROUTES = { home: screenHome, chat: screenChat, lesson: screenLesson, review: screenReview, placement: screenPlacement, weak: screenWeak, exam: screenExam, progress: screenProgress, achievements: screenAchievements, settings: screenSettings, session: screenSession };
async function route() {
  const id = (location.hash.replace(/^#\//, "") || "home").split("?")[0];
  const fn = ROUTES[id] || screenHome;
  const main = document.getElementById("main");
  renderNav(id);
  main.replaceChildren(h("p", { class: "loading" }, "Wczytuję…"));
  if (!S.pid && id !== "home") { location.hash = "#/home"; return; }
  const frag = h("div", { class: "screen" });
  const append = frag.append.bind(frag);
  frag.append = (...kids) => append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  try {
    if (S.pid && !S.settings) S.settings = await q("/api/settings").catch(() => null);
    await fn(frag);
  } catch (e) {
    frag.replaceChildren(card("Coś poszło nie tak", h("div", { class: "greet" }, mascot("thinking", 72), h("p", {}, e.message)), btn("Spróbuj ponownie", route)));
  }
  main.replaceChildren(frag);
  setStatus();
}

async function boot() {
  document.getElementById("brand").append(mascotHead(34), h("span", {}, pxText("AI Tutor", 3), h("small", {}, "English · lokalnie")));
  try { await loadProfiles(); } catch (e) { toast(e.message); }
  api("/api/system").then((st) => { S.system = st; setStatus(); }).catch(() => {});
  try {
    const r = await api("/api/session/events?since=0");
    if (r.running) {   // po odświeżeniu strony wracamy do trwającej sesji
      S.session = newSession(r.kind, !!r.text_mode);
      location.hash = "#/session";
    }
  } catch (e) { /* ignore */ }
  window.addEventListener("hashchange", route);
  route();
}
document.addEventListener("DOMContentLoaded", boot);
