"""F4.6/C1: źródła, licencje, kontrola nakładania (T-SRC-1..4)."""
import json
import shutil
import subprocess

import yaml

from tools import source_extract
from tutor import cli
from tutor.pedagogy import content as C

REAL = C.content_root()
SHA = "x" * 8


def _root(tmp_path):
    shutil.copytree(REAL / "en", tmp_path / "en")
    return tmp_path


def _tweak(root, fn, file="items/grammar/A1.yaml"):
    f = root / "en" / file
    d = yaml.safe_load(f.read_text())
    fn(d)
    f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False))


def _ref(d, src="esol", loc="chapter-slug-3.1", lic="CC-BY-4.0"):
    d[0]["provenance"] = {**d[0]["provenance"], "source": "ai_adapted", "prompt_version": "gen_item.v1",
                          "refs": [{"src": src, "loc": loc}]}
    if lic:
        d[0]["license"] = lic


def test_src_1_refs_checked(tmp_path):
    root = _root(tmp_path)
    _tweak(root, lambda d: _ref(d, src="nope"))
    assert any("nie istnieje w sources.yaml" in e for e in C.validate("en", root).errors)
    root2 = _root(tmp_path / "b")
    _tweak(root2, lambda d: _ref(d, lic=None))
    assert any("refs bez license" in e for e in C.validate("en", root2).errors)
    root3 = _root(tmp_path / "c")
    src = root3 / "en/sources.yaml"
    y = yaml.safe_load(src.read_text())
    y["sources"][0]["exclude"] = ["chapter-slug-3"]
    src.write_text(yaml.safe_dump(y))
    _tweak(root3, lambda d: _ref(d))
    assert any("wykluczoną" in e for e in C.validate("en", root3).errors)
    root4 = _root(tmp_path / "d")
    _tweak(root4, lambda d: _ref(d))
    assert C.validate("en", root4).ok


def test_src_2_sharealike(tmp_path):
    root = _root(tmp_path)
    _tweak(root, lambda d: _ref(d, src="brehe", loc="p10.1", lic="CC-BY-4.0"))
    assert any("ShareAlike" in e for e in C.validate("en", root).errors)
    root2 = _root(tmp_path / "b")
    _tweak(root2, lambda d: _ref(d, src="brehe", loc="p10.1", lic="CC-BY-SA-4.0"))
    assert C.validate("en", root2).ok
    root3 = _root(tmp_path / "c")  # mieszany CC BY + SA => SA wymagana

    def mix(d):
        _ref(d, lic="CC-BY-4.0")
        d[0]["provenance"]["refs"].append({"src": "ngsl", "loc": "x"})
    _tweak(root3, mix)
    assert any("ShareAlike" in e for e in C.validate("en", root3).errors)


def test_src_3_overlap(tmp_path):
    root = _root(tmp_path)
    ext = tmp_path / "ext"
    ext.mkdir()
    sentence = "the quick brown fox jumps over the lazy dog while the cat sleeps by the warm fire"

    def adapt(d):
        _ref(d)
        d[0]["explanation_pl"] = sentence
    _tweak(root, adapt)
    rep = C.validate("en", root)  # brak ekstraktu => ostrzeżenie, nie błąd
    assert rep.ok and any("brak lokalnego ekstraktu" in w for w in rep.warnings)
    (ext / "esol.jsonl").write_text(json.dumps({"loc": "a", "text": "Intro. " + sentence + " end"}) + "\n")
    rep = C.validate("en", root, extracted_dir=ext)
    assert any("12 kolejnych słów" in e for e in rep.errors)
    assert C.shared_run("one two three", ["one two three"]) is None


def test_src_4_no_sources_in_git_and_ai_adapted_human(tmp_path):
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=REAL.parent.parent).stdout
    assert not [x for x in out.splitlines() if x.lower().endswith((".pdf", ".epub", ".xhtml")) or "extracted/" in x]
    root = _root(tmp_path)

    def human(d):
        _ref(d)
        d[0]["review"] = {"status": "human_reviewed", "reviewer": None, "reviewed_at": None}
    _tweak(root, human)
    assert not C.validate("en", root).ok  # human_reviewed bez reviewer


def test_attribution_has_all_sources(tmp_path):
    pack = C.load("en")
    text = C.attribution_md(pack.sources)
    for s in pack.sources.sources:
        assert s.title in text and s.license in text
    assert len(pack.sources.sources) == 6 and "sup" not in {s.id for s in pack.sources.sources}
    out = []
    assert cli.content_main(["attribution", "en"], out=out.append) == 0


def test_extract_html_skips_media_and_excluded(tmp_path):
    f = tmp_path / "b.xhtml"
    f.write_text('<div class="chapter" id="c1"><h1>T</h1><p>Hello world.</p>'
                 '<div class="textbox interactive-content"><p>H5P hidden</p></div><iframe>x</iframe>'
                 '<p>After.</p></div><div class="chapter" id="c2"><p>Second</p></div>')
    frs = source_extract.extract_html(f, ["c2"])
    assert [x["loc"] for x in frs] == ["c1.1"]
    assert "hidden" not in frs[0]["text"] and "After." in frs[0]["text"]
