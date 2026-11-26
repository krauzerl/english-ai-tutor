// AI Language Tutor — grafika pikselowa rysowana w przeglądarce (bez plików graficznych).
// Wszystko powstaje z tablic znaków: font tytułowy, ikony, nauczycielka-papuga, odznaki, krajobraz.
(() => {
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}

// Jeden <path> na kolor: mniej węzłów niż prostokąt na piksel.
function pixelPaths(rows, pal, ox = 0, oy = 0) {
  const by = {};
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === "." || ch === " " || !pal[ch]) return;
    (by[ch] = by[ch] || []).push(`M${x + ox} ${y + oy}h1v1h-1z`);
  }));
  return Object.entries(by).map(([ch, d]) => svgEl("path", { d: d.join(""), fill: pal[ch] }));
}

function sprite(rows, pal, size, cls = "px") {
  const w = Math.max(...rows.map((r) => r.length)), hgt = rows.length;
  const svg = svgEl("svg", { viewBox: `0 0 ${w} ${hgt}`, width: size, height: Math.round(size * hgt / w), "aria-hidden": "true", class: cls, "shape-rendering": "crispEdges" });
  svg.append(...pixelPaths(rows, pal));
  return svg;
}

// ---------- font tytułowy 5×7 (wielkie litery, cyfry, polskie znaki) ----------
const GLYPH = {
  A: ".###.#...##...#######...##...##...#", B: "####.#...##...#####.#...##...#####.", C: ".###.#...##....#....#....#...#.###.",
  D: "####.#...##...##...##...##...#####.", E: "######....#....####.#....#....#####", F: "######....#....####.#....#....#....",
  G: ".###.#...##....#.####...##...#.###.", H: "#...##...##...#######...##...##...#", I: "#####..#....#....#....#....#..#####",
  J: "..###...#....#....#.#..#.#..#..##..", K: "#...##..#.#.#..##...#.#..#..#.#...#", L: "#....#....#....#....#....#....#####",
  M: "#...###.###.#.##.#.##...##...##...#", N: "#...###..##.#.##..###...##...##...#", O: ".###.#...##...##...##...##...#.###.",
  P: "####.#...##...#####.#....#....#....", Q: ".###.#...##...##...##.#.##..#..##.#", R: "####.#...##...#####.#.#..#..#.#...#",
  S: ".#####....#.....###.....#....#####.", T: "#####..#....#....#....#....#....#..", U: "#...##...##...##...##...##...#.###.",
  V: "#...##...##...##...##...#.#.#...#..", W: "#...##...##...##.#.##.#.###.###...#", X: "#...##...#.#.#...#...#.#.#...##...#",
  Y: "#...##...#.#.#...#....#....#....#..", Z: "#####....#...#...#...#...#....#####",
  0: ".###.#...##..###.#.###..##...#.###.", 1: "..#...##....#....#....#....#...###.", 2: ".###.#...#....#...#...#...#...#####",
  3: "####.....#....#.###.....#....#####.", 4: "...#...##..#.#.#..#.#####...#....#.", 5: "######....####.....#....##...#.###.",
  6: ".###.#....#....####.#...##...#.###.", 7: "#####....#...#...#...#....#....#...", 8: ".###.#...##...#.###.#...##...#.###.",
  9: ".###.#...##...#.####....#....#.###.",
  "!": "..#....#....#....#....#.........#..", ".": "..............................#....", ",": "......................#....#...#...",
  "-": "................###................", ":": ".......#...................#.......", "?": ".###.#...#....#...#...#.........#..",
  "/": "....#....#...#...#...#...#....#....", "'": "..#....#...........................", " ": "",
};
const MARK = { "Ą": ["A", "ogonek"], "Ę": ["E", "ogonek"], "Ć": ["C", "acute"], "Ń": ["N", "acute"], "Ó": ["O", "acute"], "Ś": ["S", "acute"], "Ź": ["Z", "acute"], "Ż": ["Z", "dot"], "Ł": ["L", "stroke"] };

function glyphRows(ch) {
  const [base, mark] = MARK[ch] || [ch, null];
  const g = GLYPH[base];
  if (g === undefined) return null;
  const body = g ? Array.from({ length: 7 }, (_, i) => g.slice(i * 5, i * 5 + 5).padEnd(5, ".")) : Array(7).fill("...");
  const top = ["....."], bottom = [".....", "....."];
  if (mark === "acute") top[0] = "...#.";
  if (mark === "dot") top[0] = "..#..";
  if (mark === "ogonek") { bottom[0] = "...#."; bottom[1] = "....#"; }
  if (mark === "stroke") { body[2] = "#.#.."; body[3] = "##..."; }
  return [...top, ...body, ...bottom];
}

// Tekst pikselowy jako SVG (dekoracja). Czytnik ekranu dostaje zwykły tekst z elementu-rodzica.
function pxText(text, size = 4, cls = "pxtext") {
  const rows = Array.from({ length: 10 }, () => "");
  for (const ch of text.toUpperCase()) {
    const g = glyphRows(ch);
    if (!g) continue;
    const w = g[0].length;
    for (let y = 0; y < 10; y++) rows[y] += (g[y] || ".".repeat(w)) + ".";
  }
  const w = rows[0].length;
  const svg = svgEl("svg", { viewBox: `0 0 ${w} 11`, width: w * size, height: 11 * size, class: cls, "aria-hidden": "true", "shape-rendering": "crispEdges", preserveAspectRatio: "xMinYMid meet" });
  const shadow = svgEl("g", { class: "pxtext-shadow" });
  shadow.append(...pixelPaths(rows, { "#": "currentColor" }, 0, 1));
  svg.append(shadow, ...pixelPaths(rows, { "#": "currentColor" }));
  return svg;
}

// ---------- ikony 12×12 ----------
const PAL = {
  k: "var(--px-ink)", w: "#f4f1e8", r: "#ff6b6b", b: "#5b8cff", g: "#3ddc97", G: "#1f9e68", y: "#ffcf4a", o: "#f08a3c",
  s: "#8b97b8", p: "#a98bff", c: "#5cc8ff", d: "#2b3557",
};
const ICONS = {
  home: ["............", ".....kk.....", "....kyyk....", "...kyyyyk...", "..kyyyyyyk..", ".kkkkkkkkkk.", "..kwwwwwwk..", "..kwkkwwwk..", "..kwkkwddk..", "..kwkkwddk..", "..kkkkkkkk..", "............"],
  chat: ["............", ".kkkkkkkkk..", ".kgggggggk..", ".kgwgwgwgk..", ".kgggggggk..", ".kkkgkkkkk..", "...kgk.kkkk.", "...kk.kcccck", "......kcwcwk", "......kcccck", ".......kkkk.", "............"],
  lesson: ["............", "..kkkkkkkk..", ".kbbbbbbbbk.", ".kbwbbbbbbk.", ".kbwbbbbbbk.", ".kbwbbyybbk.", ".kbwbbyybbk.", ".kbwbbbbbbk.", ".kkwwwwwwwk.", ".kwkkkkkkkk.", ".kk.........", "............"],
  review: ["............", "....kkkk....", "..kkyyyykk..", ".kyykkkkyyk.", ".kyk....kk..", ".kyk........", ".kyk....kyk.", "..kk....kyk.", "..kyykkkkyyk", "...kkyyyykk.", ".....kkkk...", "............"],
  level: ["............", "..........k.", ".........kk.", "........kgk.", ".......kggk.", "......kgggk.", ".....kyyggk.", "....kyyyygk.", "...koyyyygk.", "..kooyyyygk.", ".kkkkkkkkkk.", "............"],
  weak: ["............", ".....kk.....", "....krrk....", "....krrk....", "...krwrrk...", "...krwrrk...", "..krrwrrrk..", "..krrrrrrk..", ".krrrwrrrrk.", ".kkkkkkkkkk.", "............", "............"],
  exam: ["............", "..kkkkkkk...", "..kwwwwwkk..", "..kwkkkwwk..", "..kwwwwwwk..", "..kwkkkkwk..", "..kwwwwwwk..", "..kwkkgwwk..", "..kwwgwgwk..", "..kwwwgwwk..", "..kkkkkkkk..", "............"],
  progress: ["............", ".k..........", ".k.......kk.", ".k.....kkck.", ".k....kc.kk.", ".k..kkc.....", ".k.kc.......", ".kkc........", ".k..........", ".kkkkkkkkkk.", "............", "............"],
  trophy: ["............", ".kkkkkkkkkk.", ".kyyyyyyyyk.", "kkyyywyyyykk", "k.kyyyyyyk.k", ".kkyyyyyykk.", "...kyyyyk...", "....kyyk....", "....kyyk....", "...kkkkkk...", "...kooook...", "...kkkkkk..."],
  gear: ["............", ".....kk.....", "..k.kssk.k..", "..kkssssk...", "...ksskssk..", ".kssk..ksskk", ".kssk..ksskk", "...ksskssk..", "..kkssssk...", "..k.kssk.k..", ".....kk.....", "............"],
  lock: ["............", "....ssss....", "...s....s...", "...s....s...", "..ssssssss..", "..sdddddds..", "..sddssddss.", "..sddssddss.", "..sdddddds..", "..ssssssss..", "............", "............"],
  mic: ["............", ".....kk.....", "....kcck....", "....kcck....", "....kcck....", "..k.kcck.k..", "..k.kkkk.k..", "...k....k...", "....kkkk....", ".....kk.....", "....kkkk....", "............"],
  dice: ["............", ".kkkkkkkkkk.", ".kwwwwwwwwk.", ".kwkkwwwwwk.", ".kwkkwwwwwk.", ".kwwwkkwwwk.", ".kwwwkkwwwk.", ".kwwwwwkkwk.", ".kwwwwwkkwk.", ".kwwwwwwwwk.", ".kkkkkkkkkk.", "............"],
  flame: ["............", ".....k......", "....kok.....", "....kook.k..", "...kooookok.", "...kooyyook.", "..kooyyyyok.", "..koyywyyok.", "..koyyyyyok.", "...kooyyok..", "....kkkkk...", "............"],
  play: ["............", "...kk.......", "...kgkk.....", "...kgggkk...", "...kgggggk..", "...kggggggk.", "...kgggggk..", "...kgggkk...", "...kgkk.....", "...kk.......", "............", "............"],
  stop: ["............", "............", "..kkkkkkkk..", "..krrrrrrk..", "..krrrrrrk..", "..krrrrrrk..", "..krrrrrrk..", "..krrrrrrk..", "..krrrrrrk..", "..kkkkkkkk..", "............", "............"],
  star: ["............", ".....kk.....", ".....yk.....", "....kyyk....", "kkkkyyyykkkk", ".kyyyyyyyyk.", "..kyyyyyyk..", "..kyyyyyyk..", ".kyyykkyyyk.", ".kyk....kyk.", ".kk......kk.", "............"],
  check: ["............", "............", "..........k.", ".........kgk", "........kgk.", ".k.....kgk..", "kgk...kgk...", ".kgk.kgk....", "..kgkgk.....", "...kgk......", "....k.......", "............"],
};
function icon(name, size = 24) { return sprite(ICONS[name] || ICONS.lesson, PAL, size); }

// ---------- nauczycielka-papuga „Emma” w birecie ----------
const MASCOT_PAL = {
  k: "#0e1426", C: "#4b57a3", c: "#2c3570", t: "#ffcf4a", g: "#3ddc97", G: "#1f9e68", l: "#b9f6d8",
  y: "#ffcf4a", o: "#f08a3c", w: "#ffffff", e: "#0e1426", r: "#ff8a9a", m: "#7a2236",
};
const MASCOT_BASE = [
  "....kkkkkkkkkkkk....",
  "..kkCCCCCCCCCCCCkk..",
  "kkCCCCCCCCCCCCCCCCkk",
  "..kkkcccccccckkk.t..",
  "....kcccccccck...t..",
  "...kkggggggggkk..t..",
  "..kggggggggggggk.tt.",
  "..kgEEEggggEEEgk....",
  "..kgEEEggggEEEgk....",
  "..kgEEEggggEEEgk....",
  "..kgrrgyyyygrrgk....",
  "..kggggBBBBggggk....",
  "..kggggBBBBggggk....",
  "..kggggBBBBggggk....",
  "..kGgllllllllgGk....",
  ".kGGgllllllllgGGk...",
  ".kGGgllllllllgGGk...",
  "..kGgllllllllgGk....",
  "...kkggggggggkk.....",
  "....kyyk..kyyk......",
  "...kyyyk..kyyyk.....",
];
const EYES = {
  open: ["www", "wee", "www"], up: ["wee", "www", "www"], closed: ["ggg", "kkk", "ggg"], side: ["www", "eew", "www"],
};
const BEAK = { closed: ["oyyo", "goog", "gggg"], open: ["oyyo", "mmmm", "gyyg"] };

function mascotRows(eyes, beak) {
  return MASCOT_BASE.map((row, y) => {
    let r = row;
    if (y >= 7 && y <= 9) { const e = EYES[eyes][y - 7]; r = r.slice(0, 4) + e + r.slice(7, 11) + e + r.slice(14); }
    if (y >= 11 && y <= 13) { const b = BEAK[beak][y - 11]; r = r.slice(0, 7) + b + r.slice(11); }
    return r;
  });
}

// Stany: idle | listening | thinking | speaking | turn (Twoja kolej). Animacja tylko w CSS (prefers-reduced-motion ją wyłącza).
function mascot(state = "idle", size = 120) {
  const box = document.createElement("div");
  box.className = "mascot";
  box.dataset.state = state;
  const frames = [["open", "closed", "f-base"], ["closed", "closed", "f-blink"], ["open", "open", "f-talk"], ["up", "closed", "f-think"], ["side", "closed", "f-listen"]];
  for (const [e, b, cls] of frames) box.append(sprite(mascotRows(e, b), MASCOT_PAL, size, `px mascot-frame ${cls}`));
  const fx = document.createElement("div");
  fx.className = "mascot-fx";
  fx.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 3; i++) fx.append(document.createElement("i"));
  box.append(fx);
  return box;
}

// ---------- odznaki 16×16 ----------
const MEDAL = [
  "....kkkkkkkkkkkk....",
  "...kFFFFFFFFFFFFk...",
  "..kFFIIIIIIIIIIFFk..",
  ".kFFIIIIIIIIIIIIFFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFIIIIIIIIIIIIIIFk.",
  ".kFFIIIIIIIIIIIIFFk.",
  "..kFFIIIIIIIIIIFFk..",
  "...kFFIIIIIIIIFFk...",
  "....kkFFIIIIFFkk....",
  "......kkFFFFkk......",
  "........kkkk........",
];
const EMBLEM = {
  regularity: ["....w.....", "....ww....", "...www..w.", "...wwww.w.", "..wwwwwww.", ".wwwwdwwww", ".wwwdddwww", ".wwdddddww", "..wwdddww.", "...wwwww.."],
  talk_time: ["..........", ".wwwwwwww.", "wwwwwwwwww", "wwdwwdwwdw", "wwwwwwwwww", ".wwwwwwww.", "..ww......", ".ww.......", "w.........", ".........."],
  lessons: ["..........", "www....www", "wwwww.wwww", "wddwwwwddw", "wwwwwwwwww", "wddwwwwddw", "wwwwwwwwww", "wddwwwwddw", "wwwwddwwww", "....dd...."],
  reviews: ["...wwww.w.", ".ww....ww.", ".w...wwww.", "w.........", "w.........", ".........w", ".........w", ".wwww...w.", ".ww....ww.", ".w.wwww..."],
  improvement: ["....ww....", "...wwww...", "..wwwwww..", ".wwwwwwww.", "wwwwwwwwww", "...wwww...", "...wwww...", "...wwww...", "...wwww...", "...wwww..."],
  exams: [".wwwwwwww.", ".wddddddw.", ".wwwwwwww.", ".wddddwww.", ".wwwwwwww.", ".wdddwwww.", ".wwwwwdww.", ".wwwwdddw.", ".wwwwwdww.", ".........."],
  challenges: ["ww......ww", ".ww....ww.", "..ww..ww..", "...wwww...", "....ww....", "...wwww...", "..ww..ww..", "dww....wwd", "dd......dd", ".........."],
  milestones: ["ww........", "wwwwwww...", "wwwwwwwww.", "wwwwwwww..", "wwwwwww...", "ww........", "ww........", "ww........", "ww........", "dddd......"],
  mastered: ["..........", "w...ww...w", "ww..ww..ww", "www.ww.www", "wwwwwwwwww", "wwwwwwwwww", "wdwwddwwdw", "wwwwwwwwww", "..........", ".........."],
};
const CAT_COLOR = {
  regularity: ["#ff7b54", "#b8452a"], talk_time: ["#5cc8ff", "#2b78a8"], lessons: ["#3ddc97", "#1f8a5e"],
  reviews: ["#ffcf4a", "#b58a1c"], improvement: ["#a98bff", "#6a4fc2"], exams: ["#ff8ad1", "#b04c8c"],
  challenges: ["#ff6b6b", "#a83232"], milestones: ["#7fe3ff", "#3a8fb0"], mastered: ["#ffd76a", "#b58a1c"],
};
const TIER = ["#d9915a", "#d5deef", "#ffd76a"];   // brąz, srebro, złoto — kolejność progu w kategorii

function badgeArt(category, tier, earned, size = 64) {
  const [main, dark] = CAT_COLOR[category] || ["#8b97b8", "#4b5675"];
  const emblem = EMBLEM[category] || EMBLEM.milestones;
  const rows = MEDAL.map((row, y) => {
    let r = row;
    if (y >= 4 && y <= 13) { const e = emblem[y - 4]; r = r.slice(0, 5) + [...e].map((c, i) => (c === "." ? r[5 + i] : c)).join("") + r.slice(15); }
    return r;
  });
  const pal = earned
    ? { k: "#0e1426", F: TIER[Math.min(tier, 2)], I: main, w: "#ffffff", d: dark }
    : { k: "#273050", F: "#3a4466", I: "#283253", w: "#4f5b82", d: "#323c5e" };
  return sprite(rows, pal, size, `px badge-art${earned ? " earned" : ""}`);
}

// ---------- krajobraz (stały, deterministyczny) ----------
function scene(width = 240, height = 64) {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const rows = Array.from({ length: height }, () => Array(width).fill("."));
  const sky = ["a", "a", "b", "b", "c"];
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) rows[y][x] = sky[Math.min(4, Math.floor(y / (height * 0.14)))];
  for (let i = 0; i < 70; i++) { const x = Math.floor(rnd() * width), y = Math.floor(rnd() * height * 0.45); rows[y][x] = rnd() > 0.85 ? "S" : "s"; }
  // księżyc
  const mx = Math.floor(width * 0.92), my = 10;
  for (let y = -5; y <= 5; y++) for (let x = -5; x <= 5; x++) if (x * x + y * y <= 26) rows[my + y][mx + x] = (x + 2) * (x + 2) + (y - 1) * (y - 1) <= 12 ? "N" : "M";
  const hill = (base, amp, f1, f2, ch, top) => {
    for (let x = 0; x < width; x++) {
      const hgt = Math.round(base + amp * (Math.sin(x * f1) * 0.6 + Math.sin(x * f2 + 1.7) * 0.4));
      for (let y = Math.max(0, height - hgt); y < height; y++) rows[y][x] = y === height - hgt && top ? top : ch;
    }
  };
  hill(30, 7, 0.031, 0.083, "h", null);
  // wieża akademii na dalekim wzgórzu
  const tx = Math.floor(width * 0.74), tb = height - 33;
  for (let y = tb - 14; y <= tb + 2; y++) for (let x = tx - 3; x <= tx + 3; x++) rows[y][x] = "T";
  for (let x = tx - 4; x <= tx + 4; x += 2) rows[tb - 15][x] = "T";
  for (let y = tb - 22; y < tb - 15; y++) for (let x = tx - 3 + Math.floor((tb - 15 - y) / 2); x <= tx + 3 - Math.floor((tb - 15 - y) / 2); x++) rows[y][x] = "R";
  rows[tb - 10][tx] = "W"; rows[tb - 10][tx + 1] = "W"; rows[tb - 5][tx - 1] = "W";
  rows[tb - 24][tx] = "F"; rows[tb - 23][tx] = "F"; rows[tb - 24][tx + 1] = "F";
  hill(19, 5, 0.047, 0.11, "j", "J");
  hill(9, 3, 0.07, 0.15, "g", "G");
  // ścieżka i drzewka
  for (let y = height - 9; y < height; y++) { const cx = Math.floor(width * 0.55 + (height - y) * 1.6); for (let x = cx - 2 - Math.floor((y - height + 9) / 2); x <= cx + 2 + Math.floor((y - height + 9) / 2); x++) if (rows[y][x]) rows[y][x] = "P"; }
  for (const t of [0.08, 0.14, 0.43, 0.68, 0.74, 0.93]) {
    const x0 = Math.floor(width * t), base = height - 8 - Math.floor(rnd() * 4);
    for (let y = 0; y < 9; y++) for (let x = -Math.floor(y / 2); x <= Math.floor(y / 2); x++) if (rows[base - 9 + y]) rows[base - 9 + y][x0 + x] = y % 3 === 0 ? "D" : "E";
    rows[base][x0] = "B"; rows[base + 1] && (rows[base + 1][x0] = "B");
  }
  const pal = {
    a: "#0f1631", b: "#141e40", c: "#1b2a52", s: "#8fa3d9", S: "#ffffff", M: "#f2e6b8", N: "#fff7d6",
    h: "#1d3157", T: "#2a3a66", R: "#3d4f8a", W: "#ffcf4a", F: "#ff7b54", j: "#1a4a4a", J: "#22605a",
    g: "#1d6b4a", G: "#2c8a5c", P: "#c9a46a", D: "#2f9a64", E: "#1f7a4e", B: "#5a3b2a",
  };
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "scene", "aria-hidden": "true", preserveAspectRatio: "xMidYMax slice", "shape-rendering": "crispEdges" });
  svg.append(...pixelPaths(rows.map((r) => r.join("")), pal));
  return svg;
}

function mascotHead(size = 32) { return sprite(mascotRows("open", "closed").slice(0, 14), MASCOT_PAL, size); }

window.PX = { sprite, icon, pxText, mascot, mascotHead, badgeArt, scene, ICONS };
})();
