// AI Language Tutor — interfejs lokalny. Cała dydaktyka jest w Pythonie; tu tylko wyświetlanie i polecenia.
"use strict";

const TOKEN = document.querySelector('meta[name="tutor-token"]').content;
const S = { pid: null, profiles: [], system: null, settings: null, seq: 0, poll: null, session: null };

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
function fmtMin(sec) { const m = Math.round((sec || 0) / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; }

// ---------- ikony pikselowe (12×12, rysowane z tablic znaków) ----------
const PAL = { k: "var(--ink)", w: "#ffffff", r: "#c8312b", b: "#2a4fb0", g: "#2e8b3d", y: "#f2c230", o: "#e07b24", s: "#8a8a8a", p: "#7b3fa0", c: "#3aa6c9" };
const ICONS = {
  book: ["............", ".kkkkk.kkkk.", ".kbbbkkbbbk.", ".kbwbkkbwbk.", ".kbbbkkbbbk.", ".kbwbkkbwbk.", ".kbbbkkbbbk.", ".kbbbkkbbbk.", ".kkkkk.kkkk.", "....kkkk....", "............", "............"],
  chat: ["............", ".kkkkkkkkk..", ".kwwwwwwwk..", ".kwkkkkkwk..", ".kwwwwwwwk..", ".kwkkkkwwk..", ".kwwwwwwwk..", ".kkkkwkkkk..", "....kwk.....", "....kk......", "............", "............"],
  lesson: ["............", "..kkkkkkkk..", "..kggggggk..", "..kgwggggk..", "..kggwgggk..", "..kgggwggk..", "..kggggggk..", "..kkkkkkkk..", ".....kk.....", "...kkkkkk...", "............", "............"],
  review: ["............", "....kkkk....", "..kkyyyykk..", ".kyyykkyyyk.", ".kyyykyyyyk.", ".kyyykkkyyk.", ".kyyyyyyyyk.", "..kkyyyykk..", "....kkkk....", "............", "............", "............"],
  level: ["............", "..........k.", ".........kk.", "........kgk.", ".......kggk.", "......kgggk.", ".....kyyggk.", "....kyyyygk.", "...krryyygk.", "..krrryyygk.", ".kkkkkkkkkk.", "............"],
  weak: ["............", ".....kk.....", "....krrk....", "....krrk....", "...krrrrk...", "...krwwrk...", "..krrwwrrk..", "..krrrrrrk..", ".krrrwwrrrk.", ".kkkkkkkkkk.", "............", "............"],
  exam: ["............", "..kkkkkkk...", "..kwwwwwkk..", "..kwkkkwwk..", "..kwwwwwwk..", "..kwkkkkwk..", "..kwwwwwwk..", "..kwkkgwwk..", "..kwwgwgwk..", "..kwwwgwwk..", "..kkkkkkkk..", "............"],
  progress: ["............", ".k..........", ".k.......kk.", ".k.....kkck.", ".k....kc.kk.", ".k..kkc.....", ".k.kc.......", ".kkc........", ".k..........", ".kkkkkkkkkk.", "............", "............"],
  trophy: ["............", ".kkkkkkkkkk.", ".kyyyyyyyyk.", "kkyyywyyyykk", "k.kyyyyyyk.k", ".kkyyyyyykk.", "...kyyyyk...", "....kyyk....", "....kyyk....", "...kkkkkk...", "...kooook...", "...kkkkkk..."],
  gear: ["............", ".....kk.....", "..k.kssk.k..", "..kkssssk...", "...ksskssk..", ".kssk..ksskk", ".kssk..ksskk", "...ksskssk..", "..kkssssk...", "..k.kssk.k..", ".....kk.....", "............"],
  lock: ["............", "....kkkk....", "...k....k...", "...k....k...", "..kkkkkkkk..", "..ksssssk...", "..ksskssk...", "..ksskssk...", "..ksssssk...", "..kkkkkkkk..", "............", "............"],
  teacher: ["....kkkk....", "...kssssk...", "..kswwwwsk..", "..kwkwwkwk..", "..kwwwwwwk..", "..kwwkkwwk..", "...kwwwwk...", "..kkbbbbkk..", ".kbbbwwbbbk.", ".kbbbwwbbbk.", ".kbbbbbbbbk.", ".kkkkkkkkkk."],
  mic: ["............", ".....kk.....", "....krrk....", "....krrk....", "....krrk....", "..k.krrk.k..", "..k.kkkk.k..", "...k....k...", "....kkkk....", ".....kk.....", "....kkkk....", "............"],
};
function icon(name, size = 24) {
  const rows = ICONS[name] || ICONS.book;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 12 12"); svg.setAttribute("width", size); svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "px");
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === ".") return;
    const r = document.createElementNS(ns, "rect");
    r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", 1); r.setAttribute("height", 1);
    r.setAttribute("fill", PAL[ch] || "#000");
    svg.append(r);
  }));
  return svg;
}

// ---------- ramy ----------
function panel(title, ...kids) { return h("section", { class: "panel" }, h("h2", { class: "panel-title" }, title), ...kids); }
function btn(label, onclick, cls = "", ic = null) { return h("button", { class: `btn ${cls}`, onclick, type: "button" }, ic ? icon(ic, 18) : null, label); }
function bar(value, max, label) {
  const pct = max ? Math.max(0, Math.min(100, Math.round(100 * value / max))) : 0;
  const fill = h("span", { class: "bar-fill" });
  fill.style.width = pct + "%";
  return h("span", { class: "bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": max, "aria-valuenow": value, "aria-label": label || `${value}/${max}` }, fill);
}
// Bezpieczne, minimalne formatowanie wyjaśnień (nagłówki ##, listy -, `kod`) — bez innerHTML.
function rich(text) {
  const box = h("div", { class: "rich" });
  let list = null;
  const inline = (t) => t.split(/(`[^`]+`)/).map((part) => part.startsWith("`") && part.endsWith("`") && part.length > 2 ? h("code", {}, part.slice(1, -1)) : part);
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
  return h("table", { class: "grid" }, h("thead", {}, h("tr", {}, head.map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c))))));
}

const SCREENS = [
  ["home", "Start", "book"], ["chat", "Quick Chat", "chat"], ["lesson", "Lekcja", "lesson"],
  ["review", "Powtórki", "review"], ["placement", "Określ poziom", "level"], ["weak", "Słabe strony", "weak"],
  ["exam", "Egzaminy", "exam"], ["progress", "Postępy", "progress"], ["achievements", "Osiągnięcia", "trophy"],
  ["settings", "Ustawienia", "gear"],
];

function renderNav(active) {
  const nav = document.getElementById("nav");
  nav.replaceChildren(...SCREENS.map(([id, label, ic]) =>
    h("a", { href: `#/${id}`, class: id === active ? "tab active" : "tab", "aria-current": id === active ? "page" : null },
      icon(ic, 16), label)));
}

function setStatus() {
  const st = S.system;
  const parts = [];
  if (st) {
    parts.push(st.ollama ? `Ollama: działa · rozmowa: ${S.settings?.values?.chat_model || st.roles.conversation}` : "Ollama: NIE DZIAŁA — uruchom `ollama serve`");
    parts.push(st.kokoro ? "głos: Kokoro" : "głos: brak plików Kokoro (tryb tekstowy)");
    parts.push(st.audio_error ? "audio: niedostępne (tryb tekstowy)" : `audio: ${st.devices.length} urządzeń`);
  }
  if (S.session && S.session.running) parts.unshift(`● sesja: ${S.session.kind}`);
  document.getElementById("status").replaceChildren(...parts.map((p) => h("span", { class: "cell" }, p)));
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
  S.pid = id;
  try { localStorage.setItem("tutor.pid", String(id)); } catch (e) { /* ignore */ }
  api("/api/profiles/select", { pid: id }).catch(() => {});
}
function profileBox() {
  const sel = h("select", { "aria-label": "Profil ucznia", onchange: (e) => { choosePid(Number(e.target.value)); route(); } },
    S.profiles.map((p) => h("option", { value: p.id, selected: p.id === S.pid }, p.name)));
  const name = h("input", { type: "text", maxlength: 40, placeholder: "Imię nowego ucznia", "aria-label": "Nazwa nowego profilu" });
  const create = async () => {
    try { const p = await api("/api/profiles", { name: name.value }); await loadProfiles(); choosePid(p.id); route(); }
    catch (e) { toast(e.message); }
  };
  return h("div", { class: "profile-box" }, S.profiles.length ? h("label", {}, "Uczeń: ", sel) : null,
    h("span", { class: "new-profile" }, name, btn("Utwórz profil", create)));
}

// ---------- ekrany ----------
async function screenHome(main) {
  if (!S.pid) {
    main.append(panel("Witaj!", h("div", { class: "hero" }, icon("teacher", 72),
      h("div", {}, h("p", {}, "To lokalny nauczyciel angielskiego. Wszystko działa na tym komputerze."),
        h("p", {}, "Zacznij od utworzenia profilu ucznia.")))), profileBox());
    return;
  }
  const d = await q("/api/home");
  const tiles = [
    ["chat", "Quick Chat", "Swobodna rozmowa na wybrany temat", "chat"],
    ["lesson", "Lekcja", d.suggested_lesson ? "Mam propozycję lekcji dla Ciebie" : "Wybierz temat lekcji", "lesson"],
    ["review", "Powtórki", d.due_reviews ? `Do powtórki: ${d.due_reviews}` : "Brak zaległych powtórek", "review"],
    ["placement", "Określ poziom", d.placement_done ? "Wynik wstępny zapisany" : "Dobrowolnie — kiedy chcesz", "level"],
    ["weak", "Słabe strony", "Dziennik błędów i ćwiczenia", "weak"],
    ["exam", "Egzaminy", "Ścieżka ćwiczeń egzaminacyjnych", "exam"],
    ["progress", "Postępy", "Historia nauki z zapisów", "progress"],
    ["achievements", "Osiągnięcia", "Odznaki za regularność i pracę", "trophy"],
  ];
  const open = d.open_session;
  main.append(
    h("div", { class: "hero" }, icon("teacher", 72), h("div", {},
      h("h1", {}, `Cześć, ${d.profile.name}!`),
      h("p", {}, d.streak > 1 ? `Seria: ${d.streak} dni nauki z rzędu.` : "Miło Cię widzieć."),
      d.last_session ? h("p", { class: "muted" }, `Ostatnio: ${d.last_session.title}, ${fmtDate(d.last_session.started_at)}`) : null)),
    open ? h("div", { class: "callout" }, icon("review", 20), `Masz niedokończoną sesję: ${(KIND_TITLE[open.kind] || "rozmowa").toLowerCase()}. `,
      btn("Wznów", () => resume(open), "primary")) : null,
    h("div", { class: "tiles" }, tiles.map(([id, title, sub, ic]) =>
      h("a", { class: "tile", href: `#/${id}` }, icon(ic, 40), h("strong", {}, title), h("span", {}, sub)))),
    profileBox());
}

function resume(open) {
  const map = { chat: "chat", lesson: "lesson", placement: "placement", review: "review", exam: "exam" };
  if (open.kind === "chat") return startSession("chat", { topic: (open.plan && open.plan.topic && open.plan.topic.id) || "fd.cooking" });
  if (open.kind === "exam") return location.hash = "#/exam";
  startSession(map[open.kind] || "lesson", {});
}

function modeRow() {
  const cb = h("input", { type: "checkbox", id: "textmode", checked: defaultTextMode(), disabled: !voiceAvailable() });
  return h("label", { class: "check" }, cb, voiceAvailable() ? " Tryb tekstowy (bez mikrofonu i głosu)" : " Tryb tekstowy — głos niedostępny na tym komputerze");
}
const textMode = () => !!document.getElementById("textmode")?.checked;

async function screenChat(main) {
  let seed = null;
  const list = h("div", { class: "topics" });
  const custom = h("input", { type: "text", maxlength: 80, placeholder: "np. my first job, football, cats…", "aria-label": "Własny temat" });
  const minutes = h("select", { "aria-label": "Czas rozmowy" }, h("option", { value: "" }, "bez limitu"),
    [5, 10, 15, 20, 30].map((m) => h("option", { value: m }, `${m} min`)));
  const corr = correctionSelect();
  const go = (args) => startSession("chat", { ...args, minutes: minutes.value || null, correction: corr.value, text_mode: textMode() });
  const draw = async () => {
    const ts = await q("/api/topics", seed === null ? "" : `&seed=${seed}`);
    list.replaceChildren(...ts.map((t) => h("button", { class: "topic", type: "button", onclick: () => go({ topic: t.id }) },
      h("span", { class: "chip" }, t.category_pl), h("strong", {}, t.pl), h("em", {}, t.q))));
  };
  await draw();
  const hist = await q("/api/chats").catch(() => []);
  main.append(panel("Quick Chat — wybierz temat",
    note("Kliknij temat, aby od razu zacząć. Nie pasuje? Wylosuj inne albo wpisz własny."),
    list,
    h("div", { class: "row" }, btn("Wylosuj inne", () => { seed = Math.floor(Math.random() * 1e9); draw(); }, "", "review"),
      custom, btn("Rozmawiaj o tym", () => custom.value.trim() ? go({ custom: custom.value.trim() }) : toast("Wpisz temat."), "primary")),
    h("div", { class: "row" }, h("label", {}, "Czas: ", minutes), h("label", {}, "Poprawki: ", corr), modeRow()),
    note("Quick Chat nie nadaje statusu opanowania. Poprawki to sugestie modelu — mogą być błędne.", "muted")),
  hist.length ? panel("Ostatnie rozmowy", table(["Data", "Temat", "Wypowiedzi", "Czas"],
    hist.slice(0, 8).map((c) => [fmtDate(c.started_at), (c.topics || []).join(" → ") || "—", c.user_turns ?? "—", fmtMin(c.seconds_active)]))) : null);
}

function correctionSelect() {
  const cur = S.settings?.values?.correction || "summary";
  const labels = { summary: "podsumowanie na końcu", periodic: "co jakiś czas", intensive: "na bieżąco (intensywnie)" };
  return h("select", { "aria-label": "Intensywność poprawek" }, Object.entries(labels).map(([k, v]) => h("option", { value: k, selected: k === cur }, v)));
}

async function screenLesson(main) {
  const d = await q("/api/lessons");
  const sel = h("select", { "aria-label": "Temat lekcji" }, d.catalog.map((c) => h("option", { value: c.skill_id }, `${c.cefr} · ${c.can_do_pl} (${c.skill_id})`)));
  const sug = d.suggestion;
  main.append(
    panel("Proponowana lekcja", sug ? [
      h("p", {}, h("strong", {}, (d.catalog.find((c) => c.skill_id === sug.skill_id) || {}).can_do_pl || sug.skill_id), h("span", { class: "muted" }, ` (${sug.skill_id})`)),
      note(sug.reason),
      sug.provisional ? note("To propozycja — nie wynik diagnozy. Możesz wybrać inny temat poniżej.", "muted") : null,
      h("div", { class: "row" }, modeRow(), btn("Zacznij lekcję", () => startSession("lesson", { text_mode: textMode() }), "primary", "lesson")),
    ] : note("Brak lekcji z gotowymi materiałami.")),
    panel("Wybierz temat samodzielnie", h("div", { class: "row" }, sel,
      btn("Zacznij ten temat", () => startSession("lesson", { skill: sel.value, text_mode: textMode() }))),
    note(`${d.catalog.length} tematów ma komplet materiałów (wyjaśnienie i zadania). Materiały nie są jeszcze sprawdzone przez człowieka.`, "muted")));
}

async function screenReview(main) {
  const home = await q("/api/home");
  main.append(panel("Powtórki (FSRS)",
    h("p", {}, home.due_reviews ? `Do powtórki dziś: ${home.due_reviews} umiejętności.` : "Dziś nie ma zaległych powtórek."),
    note("Powtórki sprawdzają utrwalenie na nowych przykładach. Nie nadają opanowania. Limit: 20 dziennie."),
    h("div", { class: "row" }, modeRow(), btn("Zacznij powtórki", () => startSession("review", { text_mode: textMode() }), home.due_reviews ? "primary" : "", "review"))));
}

async function screenPlacement(main) {
  const d = await q("/api/placement");
  main.append(panel("Określ poziom — dobrowolnie",
    note(d.notice),
    note("Możesz przerwać w dowolnym momencie (przycisk Zakończ) i wznowić później. Ponowne sprawdzenie nie kasuje historii nauki. Niepewne rozpoznanie mowy nie obniża wyniku."),
    table(["Obszar", "Pytania w banku"], d.areas.map((a) => [areaPl(a.area), a.items])),
    h("div", { class: "row" }, modeRow(), btn(d.results.length ? "Sprawdź ponownie" : "Zacznij", () => startSession("placement", { text_mode: textMode() }), "primary", "level"))),
  panel("Wyniki (szacunek wstępny)", d.results.length ? table(["Data", "Obszar", "Wynik", "Uwagi"],
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
  if (!d.has_data) {
    main.append(panel("Dziennik słabych stron", note("Jeszcze nic tu nie ma. Wpisy pojawią się po rozmowach, lekcjach i powtórkach."), note(d.stt_uncertain.note, "muted")));
    return;
  }
  main.append(panel("Dziennik słabych stron",
    note("Każdy wpis ma etykietę wiarygodności. Sugestia modelu nie jest potwierdzonym błędem. Trend pokazujemy dopiero przy co najmniej 5 wypowiedziach w obu okresach."),
    d.errors.length ? h("div", { class: "weak-list" }, d.errors.map((e, i) => {
      const [cls, label] = REL[e.reliability] || ["none", e.reliability];
      const t = e.trend || {};
      return h("article", { class: "weak" },
        h("header", {}, h("strong", {}, `${i + 1}. ${e.category}`), h("span", { class: `badge ${cls}` }, label)),
        h("p", {}, `Wystąpienia: ${e.count} · pierwszy raz ${fmtDate(e.first_seen)} · ostatnio ${fmtDate(e.last_seen)}`),
        e.example && cls !== "stt" ? h("p", { class: "example" }, h("span", { class: "bad" }, e.example), e.correction ? [" → ", h("span", { class: "good" }, e.correction)] : null) : null,
        h("p", { class: "muted" }, `Trend (14 dni): ${t.direction || "za mało danych"} — ${t.last_14d ?? 0} obserwacji / ${t.utterances_last_14d ?? 0} wypowiedzi (poprzednio ${t.previous_14d ?? 0} / ${t.utterances_previous_14d ?? 0})`),
        e.skills.length ? btn("Ćwicz to", () => startSession("drill", { target: String(i + 1), text_mode: defaultTextMode() }), "primary", "lesson") : note("Brak materiałów do ćwiczeń dla tej kategorii.", "muted"));
    })) : null),
  d.weak_skills.length ? panel("Umiejętności z wynikiem poniżej połowy", table(["Umiejętność", "Poprawnie", ""],
    d.weak_skills.map((w) => [w.skill, `${w.correct}/${w.attempts}`, btn("Ćwicz", () => startSession("drill", { target: w.skill, text_mode: defaultTextMode() }))]))) : null,
  d.vocabulary.length ? panel("Słowa do utrwalenia", table(["Słowo", "Pomyłki"], d.vocabulary.map((w) => [w.term, w.misses]))) : null,
  panel("Niepewne rozpoznanie mowy", h("p", {}, `${d.stt_uncertain.count} — ${d.stt_uncertain.note}`)),
  d.due_reviews.length ? panel("Do powtórki", h("p", {}, d.due_reviews.join(", ")), btn("Zacznij powtórki", () => { location.hash = "#/review"; })) : null);
}

async function screenExam(main) {
  const paths = await q("/api/exams");
  for (const p of paths) {
    const r = p.readiness;
    main.append(panel(p.name,
      note(p.disclaimer),
      table(["Część", "Materiały", "Wynik ćwiczeń", "Stan"], r.sections.map((s) => {
        const cov = p.coverage.find((c) => c.section === s.section) || {};
        return [s.name, cov.status === "ok" ? `${cov.items} zadań` : (cov.note || "brak"), s.scored ? `${s.correct}/${s.scored}` : "—", s.label];
      })),
      h("ul", { class: "limits" }, [...new Set(r.limits || [])].filter((l) => l !== p.disclaimer).map((l) => h("li", {}, l))),
      p.speaking_topics.length ? h("div", {}, h("h3", {}, "Mówienie (dodatkowo, w Quick Chat)"), h("div", { class: "row" },
        p.speaking_topics.map((t) => btn(t.pl, () => startSession("chat", { custom: t.q.slice(0, 80), text_mode: defaultTextMode() }), "", "chat")))) : null,
      h("div", { class: "row" }, modeRow(), btn("Ćwicz tę ścieżkę", () => startSession("exam", { path: p.id, text_mode: textMode() }), "primary", "exam"))));
  }
  main.append(note("Matura i Cambridge: przygotowane w architekturze, bez materiałów — nie są jeszcze dostępne.", "muted"));
}

async function screenProgress(main) {
  const [p, hs, ac] = await Promise.all([q("/api/progress"), q("/api/history"), q("/api/achievements")]);
  const t = hs.totals;
  const small = (n) => (n < 5 ? " (mała próba)" : "");
  const kinds = { voice: "rozmowa", chat: "Quick Chat", lesson: "lekcja", review: "powtórki", placement: "poziom", exam: "egzamin", drill: "ćwiczenia" };
  main.append(
    panel("Podsumowanie", h("div", { class: "stats" },
      stat("Czas nauki", fmtMin(t.study_seconds)), stat("Sesje", t.sessions), stat("Ukończone lekcje", t.lessons_completed),
      stat("Powtórki", t.reviews_done), stat("Twoje wypowiedzi", t.user_turns), stat("Osiągnięcia", `${ac.earned}/${ac.total}`)),
      note("Czas nauki to przybliżenie z odstępów między zapisami. Wszystko pochodzi z bazy na tym komputerze.", "muted")),
    panel("Poziom (dobrowolne sprawdzenie)", table(["Obszar", "Stan", "Wynik", "Data"],
      p.competence.map((c) => [areaPl(c.area), c.state, c.label || "—", fmtDate(c.measured_at)]))),
    panel("Umiejętności", ...[["mastered", "Opanowane (potwierdzone przez silnik)"], ["working", "W toku"], ["struggling", "Wymagają pracy"], ["too_few", "Za mało prób"]].map(([k, label]) =>
      h("div", {}, h("h3", {}, `${label}: ${p.skills[k].length}`), p.skills[k].length ? table(["Umiejętność", "Poprawnie", "Nowe zadania"],
        p.skills[k].map((r) => [r.skill, `${r.correct}/${r.attempts}${small(r.attempts)}`, r.new_items])) : null))),
    p.changes.length ? panel("Zmiany między sesjami", table(["Umiejętność", "Poprzednio", "Ostatnio"],
      p.changes.map((c) => [c.skill, `${c.previous[0]}/${c.previous[1]}`, `${c.latest[0]}/${c.latest[1]}${small(c.latest[1])}`]))) : null,
    panel("Historia sesji", hs.sessions.length ? table(["Data", "Rodzaj", "Status", "Czas", "Wypowiedzi", "Zadania"],
      hs.sessions.map((s) => [fmtDate(s.started_at), kinds[s.kind] || s.kind, s.status, fmtMin(s.seconds), s.user_turns, s.attempts ? `${s.attempts_correct}/${s.attempts}` : "—"])) : note("Brak sesji.")));
}
function stat(label, value) { return h("div", { class: "stat" }, h("span", {}, label), h("strong", {}, String(value))); }

const CAT = { regularity: "Regularność", talk_time: "Czas rozmów", lessons: "Lekcje", reviews: "Powtórki", weakspots: "Słabe strony", challenges: "Wyzwania", milestones: "Kamienie milowe", exams: "Egzaminy", mastered: "Opanowane umiejętności" };
async function screenAchievements(main) {
  const d = await q("/api/achievements");
  if (d.new && d.new.length) toast(`Nowe osiągnięcie: ${d.new.map((n) => n.name).join(", ")}`);
  const by = {};
  d.items.forEach((i) => (by[i.category] = by[i.category] || []).push(i));
  main.append(panel(`Osiągnięcia — ${d.earned}/${d.total}`, note(d.note || "Odznaki nagradzają pracę. Nie oznaczają opanowania języka.", "muted"),
    ...Object.entries(by).map(([cat, items]) => h("div", {}, h("h3", {}, CAT[cat] || cat),
      h("div", { class: "badges" }, items.map((i) => h("div", { class: i.earned ? "badge-card earned" : "badge-card locked", title: i.description },
        h("div", { class: "medal" }, icon(i.earned ? "trophy" : "lock", 36)),
        h("strong", {}, i.name), h("span", {}, i.description),
        i.earned ? h("em", {}, `Zdobyte ${fmtDate(i.earned_at)}`) : h("span", { class: "prog" }, bar(i.progress, i.target), ` ${Math.min(i.progress, i.target)}/${i.target}`))))))));
}

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
  const theme = h("select", { "aria-label": "Wygląd", onchange: (e) => setTheme(e.target.value) },
    h("option", { value: "a", selected: currentTheme() === "a" }, "A — Klasyczny pulpit"),
    h("option", { value: "b", selected: currentTheme() === "b" }, "B — Płyta edukacyjna"));
  main.append(panel("Ustawienia ucznia", form, h("div", { class: "row" }, btn("Zapisz", save, "primary", "gear")),
    note("Model oceny zostaje bez zmian (Qwen3 8B): jego zmiana wymaga kontroli jakości. Model rozmowy musi być pobrany w Ollamie.", "muted")),
  panel("Wygląd (do akceptacji)", h("label", {}, "Wariant: ", theme), note("Zapamiętywany tylko w tej przeglądarce.", "muted")),
  panel("Ten komputer", table(["Element", "Stan"], st ? [
    ["Ollama", st.ollama ? "działa" : "nie odpowiada"], ["Pobrane modele", st.models.join(", ") || "—"],
    ["Model oceny", st.roles.evaluation || "—"], ["Głos (Kokoro)", st.kokoro ? `gotowy, ${st.voices.length} głosów` : "brak plików modelu"],
    ["Audio", st.audio_error ? `niedostępne: ${st.audio_error}` : st.devices.join("; ")]] : [])));
}

// ---------- sesja ----------
const KIND_TITLE = { chat: "Quick Chat", lesson: "Lekcja", placement: "Określ poziom", review: "Powtórki", drill: "Ćwiczenia słabej strony", exam: "Ćwiczenia egzaminacyjne" };

async function startSession(kind, args) {
  try {
    await api("/api/session/start", { pid: S.pid, kind, args });
    S.seq = 0;
    S.session = { kind, phase: null, running: true, text: !!args.text_mode, log: [], task: null, heard: null, feedback: null, goal: null, recording: false, topic: null, started: Date.now() };
    location.hash = "#/session";
  } catch (e) { toast(e.message); }
}

function screenSession(main) {
  const s = S.session;
  if (!s) { main.append(panel("Sesja", note("Brak aktywnej sesji."), btn("Na start", () => { location.hash = "#/home"; }))); return; }
  const log = h("div", { class: "log", id: "log", "aria-live": "polite", "aria-label": "Przebieg rozmowy" });
  const input = h("input", { type: "text", id: "say", maxlength: 500, placeholder: s.text ? "Napisz odpowiedź po angielsku…" : "Mów przyciskiem mikrofonu albo napisz…", "aria-label": "Twoja odpowiedź" });
  const send = async (text) => { try { await api("/api/session/send", { text }); } catch (e) { toast(e.message); } };
  const submit = () => {
    const t = input.value.trim(); if (!t) return; input.value = "";
    if (s.kind !== "chat" && s.phase !== "chat") drawEvent({ kind: "you", text: t, seq: -1 }, true);   // ćwiczenia: silnik nie powtarza odpowiedzi
    send(t);
  };
  S.answer = (t) => { input.value = t; submit(); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const mic = s.text ? null : btn("Mów", () => send(""), "mic", "mic");
  if (mic) mic.id = "micbtn";
  const quick = s.kind === "chat"
    ? [["Powtórz", "Could you repeat that, please?"], ["Wyjaśnij", "Could you explain that in simpler words?"], ["Zmień temat", "Can we change the topic?"]]
    : ["exam", "placement"].includes(s.kind) ? [["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?"]]
      : [["Podpowiedź", "Could you explain, please?"], ["Nie wiem", "I don't know"], ["Pomiń", "Can we skip this?"]];
  const side = h("aside", { class: "side", id: "side" });
  main.append(h("div", { class: "session" },
    h("div", { class: "session-main" },
      h("div", { class: "session-head" }, icon("teacher", 40), h("div", {}, h("h1", {}, KIND_TITLE[s.kind] || s.kind), h("p", { class: "muted", id: "sstate" }, "Łączę z nauczycielem…"))),
      log,
      h("div", { class: "composer" }, mic, input, btn("Wyślij", submit, "primary")),
      h("div", { class: "row quick" }, quick.map(([l, t]) => btn(l, () => send(t))), btn("Zakończ", () => api("/api/session/stop", {}).catch((e) => toast(e.message)), "danger"))),
    side));
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
  if (k === "task") { s.task = ev; s.heard = null; s.feedback = null; }
  if (k === "heard") s.heard = ev.text;
  if (k === "feedback") s.feedback = ev.text;
  if (k === "goal") s.goal = ev.text.split("\n")[0];
  if (k === "recording") s.recording = true;
  if (k === "info" && ev.text.trim().startsWith("Teraz krótka rozmowa")) s.phase = "chat";
  if (k === "you" || k === "tutor" || k === "prompt" || k === "end") s.recording = false;
  if (k === "info" && ev.text.startsWith("Quick Chat — temat:")) s.topic = ev.text.replace("Quick Chat — temat:", "").split("(")[0].trim().replace(/\.$/, "");
  if (k === "notice" && ev.text.startsWith("nowy temat:")) s.topic = ev.text.replace("nowy temat:", "").trim();
  if (!log) return;
  const skip = ["prompt", "start", "metric", "listening"];
  if (skip.includes(k)) return;
  if (k === "info" && /^(\[Enter\]|Profil:)/.test(ev.text)) return;
  const last = log.lastElementChild;
  if (k === "tutor" && last && last.classList.contains("tutor") && last.dataset.seq == ev.seq - 1) {   // jedna wypowiedź, kilka zdań
    last.querySelector("p").textContent += " " + ev.text; last.dataset.seq = ev.seq; return;
  }
  let el;
  if (k === "tutor") el = h("div", { class: "msg tutor" }, h("b", {}, "Nauczyciel"), h("p", {}, ev.text));
  else if (k === "you") el = h("div", { class: "msg you" }, h("b", {}, "Ty"), h("p", {}, ev.text));
  else if (k === "task") el = h("div", { class: "msg task" }, h("b", {}, `Zadanie ${ev.index}/${ev.total}${ev.tag ? " · " + ev.tag : ""}`), h("pre", {}, ev.text));
  else if (k === "goal") el = h("div", { class: "msg goal" }, rich(ev.text));
  else if (k === "error") el = h("div", { class: "msg error", role: "alert" }, h("b", {}, "Błąd"), h("p", {}, ev.text));
  else if (k === "end") el = h("div", { class: "msg sys" }, ev.code ? "Sesja zakończona z błędem." : "Sesja zamknięta. Wyniki zapisano; przerwaną lekcję, powtórki lub sprawdzenie poziomu możesz wznowić tym samym przyciskiem.");
  else if (k === "recording") el = h("div", { class: "msg sys rec" }, "● Nagrywam — kliknij „Stop”, gdy skończysz.");
  else el = h("div", { class: `msg ${k}` }, h("pre", {}, ev.text.trim()));
  el.dataset.seq = ev.seq;
  log.append(el);
  log.scrollTop = log.scrollHeight;
}

function drawSide() {
  const s = S.session, side = document.getElementById("side");
  if (!side) return;
  document.querySelectorAll(".composer input, .composer button, .quick button").forEach((b) => { b.disabled = !s.running; });
  const mic = document.getElementById("micbtn");
  if (mic) { mic.lastChild.textContent = s.recording ? "Stop" : "Mów"; mic.classList.toggle("on", s.recording); mic.disabled = !s.running; }
  const st = document.getElementById("sstate");
  if (st) st.textContent = s.running ? (s.recording ? "● nagrywanie" : (s.text ? "tryb tekstowy" : "tryb głosowy — kliknij „Mów”, potem „Stop”")) : "zakończona";
  const parts = [];
  if (s.kind === "chat") {
    const min = Math.floor((Date.now() - s.started) / 60000);
    parts.push(h("h3", {}, "Temat"), h("p", { class: "big" }, s.topic || "…"), h("p", { class: "muted" }, `Czas: ${min} min`),
      note("Powiedz albo napisz „change the topic”, aby zmienić temat. Podsumowanie poprawek pojawi się na końcu.", "muted"));
  } else {
    if (s.goal) parts.push(h("h3", {}, "Cel"), h("p", {}, s.goal));
    if (s.phase === "chat") parts.push(h("h3", {}, "Rozmowa po ćwiczeniach"), note("Użyj tego, co ćwiczysz. „Zakończ” zamyka lekcję i pokazuje podsumowanie poprawek.", "muted"));
    else if (s.task) {
      const opts = [...s.task.text.matchAll(/^\s+\d+\.\s+(.+)$/gm)].map((m) => m[1].trim());
      const stem = s.task.text.replace(/\n\s+\d+\.\s+.+/g, "");
      parts.push(h("h3", {}, `Zadanie ${s.task.index} z ${s.task.total}`), bar(s.task.index - 1, s.task.total, "Postęp lekcji"), h("pre", { class: "task-text" }, stem),
        opts.length && s.running ? h("div", { class: "options" }, opts.map((o) => btn(o, () => S.answer(o)))) : null);
    }
    if (s.heard) parts.push(h("h3", {}, "Rozpoznano"), h("p", {}, s.heard));
    if (s.feedback) parts.push(h("h3", {}, "Ocena"), h("p", { class: s.feedback.startsWith("✓") ? "good" : /^(✗|Poprawna odpowiedź)/.test(s.feedback) ? "bad" : "" }, s.feedback));
    if (!parts.length) parts.push(note("Za chwilę pojawi się pierwsze zadanie.", "muted"));
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
    drawSide(); setStatus();
    if (!r.running) return;
  } catch (e) { toast(e.message); }
  S.poll = setTimeout(pollSession, 350);
}

// ---------- wygląd ----------
function currentTheme() {
  const u = new URLSearchParams(location.search).get("theme");   // ?theme=a|b — porównanie wariantów
  if (u === "a" || u === "b") return u;
  try { return localStorage.getItem("tutor.theme") || "a"; } catch (e) { return "a"; }
}
function setTheme(t) {
  document.body.className = `theme-${t === "b" ? "b" : "a"}`;
  try { localStorage.setItem("tutor.theme", t); } catch (e) { /* ignore */ }
}

// ---------- routing ----------
const ROUTES = { home: screenHome, chat: screenChat, lesson: screenLesson, review: screenReview, placement: screenPlacement, weak: screenWeak, exam: screenExam, progress: screenProgress, achievements: screenAchievements, settings: screenSettings, session: screenSession };
async function route() {
  const id = (location.hash.replace(/^#\//, "") || "home").split("?")[0];
  const fn = ROUTES[id] || screenHome;
  const main = document.getElementById("main");
  renderNav(id);
  document.getElementById("who").textContent = S.profiles.find((p) => p.id === S.pid)?.name || "";
  main.replaceChildren(h("p", { class: "muted" }, "Wczytuję…"));
  if (!S.pid && id !== "home") { location.hash = "#/home"; return; }
  const frag = h("div", { class: "screen" });
  const append = frag.append.bind(frag);
  frag.append = (...kids) => append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  try {
    if (S.pid && !S.settings) S.settings = await q("/api/settings").catch(() => null);
    await fn(frag);
  } catch (e) {
    frag.replaceChildren(panel("Coś poszło nie tak", h("div", { class: "hero" }, icon("weak", 48), h("p", {}, e.message)), btn("Spróbuj ponownie", route)));
  }
  main.replaceChildren(frag);
  setStatus();
}

async function boot() {
  setTheme(currentTheme());
  try { await loadProfiles(); } catch (e) { toast(e.message); }
  api("/api/system").then((st) => { S.system = st; setStatus(); }).catch(() => {});
  try {
    const r = await api("/api/session/events?since=0");
    if (r.running) {   // po odświeżeniu strony wracamy do trwającej sesji
      S.session = { kind: r.kind, phase: null, running: true, text: !!r.text_mode, log: [], task: null, heard: null, feedback: null, goal: null, recording: false, topic: null, started: Date.now() };
      location.hash = "#/session";
    }
  } catch (e) { /* ignore */ }
  window.addEventListener("hashchange", route);
  route();
  document.querySelector(".title-icon").append(icon("book", 16));
}
document.addEventListener("DOMContentLoaded", boot);
