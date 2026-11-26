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
  k: "var(--px-ink)", w: "#f3ead7", r: "#e98265", b: "#79c9bf", g: "#a6d676", G: "#6e9e48", y: "#f2be63", o: "#d98a4e",
  s: "#aa9f8d", p: "#c9a2d8", c: "#79c9bf", d: "#40375a",
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

// ---------- maskotka: żaba-wędrowniczka (nazwa robocza „Kumka”) ----------
// Klatki wygenerowane z kształtów (kapelusz podróżnika, chusta, poziome źrenice); jedna sylwetka, osiem klatek.
const FROG_PAL = {
  k: "#191624", g: "#A6D676", G: "#6E9E48", l: "#E4F1B9", w: "#F7F0DF", e: "#191624", h: "#D9A35F", H: "#A8743A",
  b: "#E98265", s: "#79C9BF", S: "#4E9C93", m: "#5B2B3A", c: "#F0A08A",
};
const FROG = {
  idle: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggwwwggggggggggwwwggk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kwwwwwwwggggggwwwwwwwk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kggwwwggggggggggwwwggk.....",
    "....kggggggmggggggggmggggggk....",
    "....kgggggggmmmmmmmmgggggggk....",
    "....kggggccggggggggggccggggk....",
    "...kggggggggggggggggggggggggk...",
    "....kggggggggllllllggggggggk....",
    "....kgggssssssssssssssssgggk....",
    "....kgggSSSSSSSSSSSSSSSSgggk....",
    ".....kgggsssllllllllllggggk.....",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  blink: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kgeeeeeggggggggeeeeegk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    "....kggggggmggggggggmggggggk....",
    "....kgggggggmmmmmmmmgggggggk....",
    "....kggggccggggggggggccggggk....",
    "...kggggggggggggggggggggggggk...",
    "....kggggggggllllllggggggggk....",
    "....kgggssssssssssssssssgggk....",
    "....kgggSSSSSSSSSSSSSSSSgggk....",
    ".....kgggsssllllllllllggggk.....",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  listening: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggwwwggggggggggwwwggk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kwwwwwwwggggggwwwwwwwk.....",
    ".....kweeewwwggggggweeewwwk.....",
    "kkk..kweeewwwggggggweeewwwk.....",
    "gggk.kgwwwwwggggggggwwwwwgk.....",
    "gggk.kggwwwggggggggggwwwggk.....",
    "kggkkggggggggggmmggggggggggk....",
    "kggkkggggggggggmmggggggggggk....",
    "kggkkggggccggggggggggccggggk....",
    "kggkggggggggggggggggggggggggk...",
    "kggkkggggggggllllllggggggggk....",
    "kgggkgggssssssssssssssssgggk....",
    "kgggkgggSSSSSSSSSSSSSSSSgggk....",
    ".kkk.kgggsssllllllllllggggk.....",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  thinking: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggwwwggggggggggwwwggk.....",
    ".....kgwweeeggggggggwweeegk.....",
    ".....kwwweeewggggggwwweeewk.....",
    ".....kwwwwwwwggggggwwwwwwwk.....",
    ".....kwwwwwwwggggggwwwwwwwk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kggwwwggggggggggwwwggk.....",
    "....kggggggggggggggggggggggk....",
    "....kggggggggmmmmmmggggggggk....",
    "....kggggccggggggggggccggggk....",
    "...kggggggggggggggggggggggggk...",
    "....kggggggggllllllggggggggk....",
    "....kgggssssssssssssssssgggk....",
    "....kgggSSSSSSSSSSSSSSSSgggk....",
    ".....kgggsssllllllllllggggk.....",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  speaking: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggwwwggggggggggwwwggk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kwwwwwwwggggggwwwwwwwk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kggwwwggggggggggwwwggk.....",
    "....kggggggggmmmmmmggggggggk....",
    "....kggggggggmmmmmmggggggggk....",
    "....kggggccggmmbbmmggccggggk....",
    "...kggggggggggggggggggggggggk...",
    "....kggggggggllllllggggggggk....",
    "....kgggssssssssssssssssgggk....",
    "....kgggSSSSSSSSSSSSSSSSgggk....",
    ".....kgggsssllllllllllggggk.....",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  encouraging: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kwweeewwggggggwweeewwk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kggwwwggggggggggwwwggk.....",
    "....kggggggmggggggggmggggggkkkk.",
    "....kgggggggmmmmmmmmgggggggkgggk",
    "....kggggccggggggggggccggggkgggk",
    "...kggggggggggggggggggggggggkggk",
    "....kggggggggllllllggggggggkkggk",
    "....kgggssssssssssssssssgggkkggk",
    "....kgggSSSSSSSSSSSSSSSSgggggggk",
    ".....kgggsssllllllllllggggkgggk.",
    "......kggssslllllllllllggk.kkk..",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  success: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggggggggggggggggggggk.....",
    ".....kggggggggggggggggggggk.....",
    "kkk..kgggeggggggggggggegggk.kkk.",
    "gggk.kggegeggggggggggegeggkkgggk",
    "gggk.kgegggeggggggggegggegkkgggk",
    "kggk.kggggggggggggggggggggk.kggk",
    "kggk.kggggggggggggggggggggk.kggk",
    "kggkkggggggmmmmmmmmmmggggggkkggk",
    "kggkkgggggggmmmmmmmmgggggggkkggk",
    "kggkkggggccgmmbbbbmmgccggggkkggk",
    "kggkggggggggggggggggggggggggkggk",
    "kggkkggggggggllllllggggggggkkggk",
    "kgggkgggssssssssssssssssgggggggk",
    "kgggkgggSSSSSSSSSSSSSSSSggggggk.",
    ".kkk.kgggsssllllllllllggggkkkk..",
    "......kggssslllllllllllggk......",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
  explaining: [
    "...........kkkkkkkkkk...........",
    "..........khHHHHHHHHhk..........",
    "..........khhhhhhhhhhk..........",
    "..........khhhhhhhhhhk..........",
    "..........kbbbbbbbbbbk..........",
    ".......kkkkhhhhhhhhhhkkkk.......",
    "......kHhhhhhhhhhhhhhhhhHk......",
    "......kHHHHHHHHHHHHHHHHHHk......",
    ".....kggwwwggggggggggwwwggk.....",
    ".....kgwwwwwggggggggwwwwwgk.....",
    ".....kwwwwwwwggggggwwwwwwwkkkk..",
    ".....kwweeewwggggggwweeewwkgggk.",
    ".....kwweeewwggggggwweeewwkgggk.",
    ".....kgwwwwwggggggggwwwwwgkkggk.",
    ".....kggwwwggggggggggwwwggkkggk.",
    "....kggggggggmmmmmmggggggggkggk.",
    "....kggggggggmmmmmmggggggggkggk.",
    "....kggggccggmmbbmmggccggggkggk.",
    "...kggggggggggggggggggggggggggk.",
    "....kggggggggllllllggggggggkggk.",
    "....kgggssssssssssssssssgggkggk.",
    "....kgggSSSSSSSSSSSSSSSSggggggk.",
    ".....kgggsssllllllllllggggkggk..",
    "......kggssslllllllllllggk.kk...",
    ".......kgsssllllllllllggk.......",
    "......kkkslSllllllllllgkkk......",
    ".....kggggggllllllllggggggk.....",
    ".....kggggggkllllllkggggggk.....",
    ".....kgkgkgk.kkkkkk.kgkgkgk.....",
    "......k.k.k..........k.k.k......",
  ],
};

// Stany: idle | listening | thinking | speaking | encouraging | success | explaining (+ turn = idle).
// Animacje tylko w CSS; prefers-reduced-motion je wyłącza, a stan nadal widać po klatce i podpisie.
function mascot(state = "idle", size = 120) {
  const box = document.createElement("div");
  box.className = "mascot";
  box.dataset.state = state;
  for (const [name, rows] of Object.entries(FROG)) box.append(sprite(rows, FROG_PAL, size, `px mascot-frame f-${name}`));
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
  conversation: ["..........", ".wwwww....", "wwwwwww...", "wwdwdww.w.", "wwwwwww.ww", ".wwwww.www", "..w...wwww", ".w....wdww", "......wwww", ".......ww."],
  assessment: ["...wwww...", "..w....w..", ".w..ww..w.", ".w.wddw.w.", ".w.wddw.w.", ".w..ww..w.", "..w....w..", "...wwww.w.", ".......w.w", "........w."],
  secrets: ["...wwww...", "..ww..ww..", "......ww..", ".....ww...", "....ww....", "....ww....", "..........", "....ww....", "....ww....", ".........."],
};
// Pozycje „run” na pierścieniu medalu: wzór z kodu odznaki czyni każdą ikonę rozpoznawalną (nie 150 kopii).
const RUNES = [[2, 6], [2, 9], [2, 12], [3, 4], [3, 15], [6, 2], [9, 2], [12, 2], [6, 17], [9, 17], [12, 17], [15, 4],
  [15, 15], [16, 7], [16, 10], [16, 12]];
function hash(str) { let x = 2166136261; for (const c of String(str)) { x ^= c.charCodeAt(0); x = Math.imul(x, 16777619); } return x >>> 0; }
const CAT_COLOR = {
  regularity: ["#e98265", "#9c4a33"], talk_time: ["#79c9bf", "#3c7f77"], lessons: ["#a6d676", "#5d8a3a"],
  reviews: ["#f2be63", "#9c7424"], improvement: ["#c9a2d8", "#7d5a8c"], exams: ["#e7a0b4", "#93506a"],
  challenges: ["#d9715a", "#8a3a2a"], milestones: ["#8fb8d8", "#4a6f8c"], mastered: ["#f2be63", "#9c7424"],
  conversation: ["#79c9bf", "#3c7f77"], assessment: ["#b9b0e0", "#5f5690"], secrets: ["#2f2a40", "#f2be63"],
  competence: ["#f2be63", "#9c7424"],
};
const TIER = ["#c98a55", "#d9d3c4", "#f2be63"];   // brąz, srebro, złoto — kolejność progu w kategorii

function badgeArt(category, tier, earned, size = 64, code = "") {
  const [main, dark] = CAT_COLOR[category] || ["#8b97b8", "#4b5675"];
  const emblem = EMBLEM[category] || EMBLEM.milestones;
  const hx = hash(code);
  const rows = MEDAL.map((row, y) => {
    let r = row;
    if (y >= 4 && y <= 13) { const e = emblem[y - 4]; r = r.slice(0, 5) + [...e].map((c, i) => (c === "." ? r[5 + i] : c)).join("") + r.slice(15); }
    return [...r];
  });
  if (code) RUNES.forEach(([y, x], i) => { if ((hx >>> i) & 1 && rows[y][x] === "I") rows[y][x] = "d"; });
  const pal = earned
    ? { k: "#0e1426", F: TIER[Math.min(tier, 2)], I: main, w: "#ffffff", d: dark }
    : { k: "#211c2e", F: "#40375a", I: "#342d47", w: "#5d5277", d: "#40375a" };
  return sprite(rows.map((r) => r.join("")), pal, size, `px badge-art${earned ? " earned" : ""}`);
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
  hill(24, 5, 0.031, 0.083, "h", null);
  // wieża akademii na dalekim wzgórzu
  const tx = Math.floor(width * 0.74), tb = height - 26;
  for (let y = tb - 14; y <= tb + 2; y++) for (let x = tx - 3; x <= tx + 3; x++) rows[y][x] = "T";
  for (let x = tx - 4; x <= tx + 4; x += 2) rows[tb - 15][x] = "T";
  for (let y = tb - 22; y < tb - 15; y++) for (let x = tx - 3 + Math.floor((tb - 15 - y) / 2); x <= tx + 3 - Math.floor((tb - 15 - y) / 2); x++) rows[y][x] = "R";
  rows[tb - 10][tx] = "W"; rows[tb - 10][tx + 1] = "W"; rows[tb - 5][tx - 1] = "W";
  rows[tb - 24][tx] = "F"; rows[tb - 23][tx] = "F"; rows[tb - 24][tx + 1] = "F";
  hill(15, 4, 0.047, 0.11, "j", "J");
  hill(8, 2, 0.07, 0.15, "g", "G");
  // ścieżka i drzewka
  for (let y = height - 9; y < height; y++) { const cx = Math.floor(width * 0.55 + (height - y) * 1.6); for (let x = cx - 2 - Math.floor((y - height + 9) / 2); x <= cx + 2 + Math.floor((y - height + 9) / 2); x++) if (rows[y][x]) rows[y][x] = "P"; }
  for (const t of [0.08, 0.14, 0.43, 0.68, 0.74, 0.93]) {
    const x0 = Math.floor(width * t), base = height - 8 - Math.floor(rnd() * 4);
    for (let y = 0; y < 9; y++) for (let x = -Math.floor(y / 2); x <= Math.floor(y / 2); x++) if (rows[base - 9 + y]) rows[base - 9 + y][x0 + x] = y % 3 === 0 ? "D" : "E";
    rows[base][x0] = "B"; rows[base + 1] && (rows[base + 1][x0] = "B");
  }
  const pal = {   // zmierzch: śliwka → bakłażan → ciepły pas nad horyzontem
    a: "#1f1a2c", b: "#292338", c: "#4a3550", s: "#cbbfae", S: "#f3ead7", M: "#f2be63", N: "#f8dca0",
    h: "#3d4f63", T: "#4a3f5e", R: "#e98265", W: "#f2be63", F: "#79c9bf", j: "#3f8a80", J: "#79c9bf",
    g: "#6e9e48", G: "#a6d676", P: "#e0c08a", D: "#8cc063", E: "#4f7a36", B: "#6b4a3a",
  };
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "scene", "aria-hidden": "true", preserveAspectRatio: "xMidYMax slice", "shape-rendering": "crispEdges" });
  svg.append(...pixelPaths(rows.map((r) => r.join("")), pal));
  return svg;
}

function mascotHead(size = 32) { return sprite(FROG.idle.slice(0, 22), FROG_PAL, size); }

window.PX = { sprite, icon, pxText, mascot, mascotHead, badgeArt, scene, ICONS };
})();
