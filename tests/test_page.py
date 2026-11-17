from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.browser import dump_dom, find_browser
from tests.helpers import ROOT, make_graph
from taskgraph import model

PAGE = ROOT / "plugin" / "page" / "taskgraph.html"


class _Dom(HTMLParser):
    """A dumped DOM: start tags with attributes, visible text (no <script>/<style>), #err text."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self._text: list[str] = []
        self._err: list[str] = []
        self._in_err = 0
        self._in_code = 0
        self.feed(html)
        self.close()
        self.text = "".join(self._text)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        self.tags.append((tag, a))
        if tag in ("script", "style"):
            self._in_code += 1
        if self._in_err:
            self._in_err += 1
        elif a.get("id") == "err":
            self._in_err = 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._in_code:
            self._in_code -= 1
        if self._in_err:
            self._in_err -= 1

    def handle_data(self, data):
        if self._in_code:
            return
        self._text.append(data)
        if self._in_err:
            self._err.append(data)

    def first(self, tag: str, **attrs) -> dict | None:
        """Attributes of the first `tag` whose attributes match (data_dir= means data-dir=)."""
        for t, a in self.tags:
            if t == tag and all(a.get(k.replace("_", "-")) == v for k, v in attrs.items()):
                return a
        return None

    def nodes(self) -> dict[str, set[str]]:
        """data-id -> class tokens of every graph node."""
        out = {}
        for t, a in self.tags:
            classes = set(a.get("class", "").split())
            if t == "g" and "node" in classes and "data-id" in a:
                out[a["data-id"]] = classes
        return out

    def err_text(self) -> str:
        return "".join(self._err).strip()


def _classes(attrs: dict | None) -> set[str]:
    return set((attrs or {}).get("class", "").split())


def _fixture_reload(first: dict, later: str) -> str:
    """taskgraph.js: `first` on its first run, the JS expression `later` on every run after it."""
    return ("window.__tgLoads = (window.__tgLoads || 0) + 1;\n"
            "window.TASKGRAPH = window.__tgLoads < 2 ? %s : %s;\n"
            % (json.dumps(first, ensure_ascii=False), later))


def _item(iid: str, deps: list) -> dict:
    return {"id": iid, "title": "Item " + iid, "group": "G", "session": None, "stage": -1,
            "status": "todo", "wait": "", "deps": deps, "summary": "", "details": [],
            "links": [], "files": []}


class BrowserPresenceTest(unittest.TestCase):
    """In CI (TASKGRAPH_REQUIRE_BROWSER=1) a missing browser fails instead of skipping the page tests."""

    @unittest.skipUnless(os.environ.get("TASKGRAPH_REQUIRE_BROWSER"), "browser not required")
    def test_browser_found(self):
        self.assertIsNotNone(find_browser(),
                             "TASKGRAPH_REQUIRE_BROWSER is set, but no Chromium-based browser "
                             "was found (set TASKGRAPH_BROWSER)")


@unittest.skipIf(find_browser() is None, "no Chromium-based browser (set TASKGRAPH_BROWSER)")
class PageTests(unittest.TestCase):
    def _open(self, data_js: str, query: str = "", budget_ms: int = 2000) -> _Dom:
        folder = Path(tempfile.mkdtemp(prefix="fm-page-"))
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copyfile(PAGE, folder / "taskgraph.html")
        with open(folder / "taskgraph.js", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data_js)
        return _Dom(dump_dom(folder / "taskgraph.html", query, budget_ms))

    def _open_graph(self, graph: dict, query: str = "", budget_ms: int = 2000) -> _Dom:
        return self._open(model.dump(graph), query, budget_ms)

    def test_page_renders_items(self):
        g = make_graph()
        g["task"]["rev"] = 7
        g["task"]["updated"] = "2026-01-02T03:04"
        dom = self._open_graph(g)
        self.assertEqual(sorted(dom.nodes()), ["1", "2", "3", "4"])
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "7")
        self.assertIn("updated 2026-01-02 03:04", dom.text)

    def test_page_brand_mark_and_tab_title(self):
        dom = self._open_graph(make_graph(), "?lang=en")
        icon = dom.first("link", rel="icon")
        self.assertIsNotNone(icon)
        self.assertTrue(icon["href"].startswith("data:image/svg+xml,"))
        self.assertIsNotNone(dom.first("svg", **{"class": "mark"}))
        self.assertIn("Task map K-1 · Flagman", dom.text)
        self.assertEqual(dom.err_text(), "")

    def test_page_conflict_between_columns_stays_between_items(self):
        # 2 and 3 are in different layers: the line joins the two boxes directly instead of
        # looping back past both, and its ends stay off the middle of the sides (arrow ports)
        g = make_graph()
        g["conflicts"] = [{"a": "3", "b": "2", "why": "both edit one file"}]
        for layout, w, h in (("lr", 168, 50), ("tb", 156, 50)):
            dom = self._open_graph(g, "?lang=en&dir=" + layout)
            self.assertEqual(dom.err_text(), "")
            at = {}
            for t, a in dom.tags:
                if t == "g" and "node" in _classes(a) and a.get("data-id") in ("2", "3"):
                    x, y = a["transform"].split("(")[1].rstrip(")").split(",")
                    at[a["data-id"]] = (float(x), float(y))
            xs, ys = [p[0] for p in at.values()], [p[1] for p in at.values()]
            path = dom.first("path", **{"class": "cf"})
            nums = [float(n) for n in path["d"].replace("M", " ").replace("C", " ")
                    .replace("L", " ").replace(",", " ").split()]
            for x, y in zip(nums[0::2], nums[1::2]):
                self.assertTrue(min(xs) - 1 <= x <= max(xs) + w + 1, (layout, x, path["d"]))
                self.assertTrue(min(ys) - 1 <= y <= max(ys) + h + 1, (layout, y, path["d"]))
                # not the middle of a box side, where dependency arrows enter and leave
                for bx, by in at.values():
                    if layout == "lr" and x in (bx, bx + w):
                        self.assertGreater(abs(y - (by + h / 2)), h * 0.35, (layout, y, path["d"]))
                    if layout == "tb" and y in (by, by + h):
                        self.assertGreater(abs(x - (bx + w / 2)), w * 0.35, (layout, x, path["d"]))
            label = dom.first("text", **{"class": "cflabel"})
            self.assertTrue(min(xs) <= float(label["x"]) <= max(xs) + w, (layout, label["x"]))

    def test_page_states(self):
        nodes = self._open_graph(make_graph()).nodes()
        self.assertIn("st-ready", nodes["3"])
        self.assertIn("st-blocked", nodes["4"])
        self.assertIn("st-wait-me", nodes["2"])
        self.assertIn("st-done", nodes["1"])

    def test_page_review_status(self):
        g = make_graph()
        g["items"][2]["status"] = "review"
        g["sessions"][0]["state"] = "review"
        dom = self._open_graph(g, "?lang=ru")
        self.assertIn("st-review", dom.nodes()["3"])
        self.assertIn("На ревью", dom.text)
        self.assertIn("ждут ревью или мерджа", dom.text)
        self.assertEqual(dom.err_text(), "")
        en = self._open_graph(g, "?lang=en")
        self.assertIn("In review", en.text)
        self.assertIn("waiting for review or merge", en.text)
        self.assertEqual(en.err_text(), "")

    def test_page_stage_pipe_marks_reached_stages(self):
        # `stage` is the last stage reached: item 2 is at stage 1, so stages 0-1 are done
        # and stage 2 is the one in progress, the same as the dots on the graph node.
        dom = self._open_graph(make_graph(), "#2")
        start = next(i for i, (t, a) in enumerate(dom.tags)
                     if t == "div" and "pipe" in _classes(a))
        spans = [a.get("class", "") for t, a in dom.tags[start + 1:] if t == "span"][:6]
        self.assertEqual(spans, ["done", "done", "cur", "", "", ""])

    def test_page_lang_en(self):
        en = self._open_graph(make_graph("ru"), "?lang=en")
        self.assertEqual(en.first("html").get("lang"), "en")
        self.assertIn("Waiting on you", en.text)
        self.assertNotIn("Ждёт тебя", en.text)
        self.assertEqual(en.err_text(), "")

        ru = self._open_graph(make_graph("ru"))
        self.assertEqual(ru.first("html").get("lang"), "ru")
        self.assertIn("Ждёт тебя", ru.text)
        self.assertNotIn("Waiting on you", ru.text)

        # No query and nothing stored: the graph's own lang decides.
        data_en = self._open_graph(make_graph("en"))
        self.assertEqual(data_en.first("html").get("lang"), "en")
        self.assertIn("Waiting on you", data_en.text)

    def test_page_reload_on_rev(self):
        first = make_graph()
        first["task"]["rev"] = 1
        later = make_graph()
        later["task"]["rev"] = 2
        later["items"].append(_item("5", [{"id": "3", "note": ""}]))
        data_js = _fixture_reload(first, json.dumps(later, ensure_ascii=False))
        dom = self._open(data_js, "?poll=500&dir=tb#3", budget_ms=4000)
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "2")
        nodes = dom.nodes()
        self.assertEqual(sorted(nodes), ["1", "2", "3", "4", "5"])
        self.assertIn("sel", nodes["3"])
        self.assertIn("on", _classes(dom.first("button", data_dir="tb")))
        self.assertNotIn("on", _classes(dom.first("button", data_dir="lr")))

    def test_page_reload_keeps_zoom(self):
        # The second run of the data script zooms the graph with the wheel (as the user would) and
        # records the viewBox, then hands over rev 2: the redraw keeps that viewBox, no fit().
        first = make_graph()
        first["task"]["rev"] = 1
        later = make_graph()
        later["task"]["rev"] = 2
        later["items"].append(_item("5", [{"id": "3", "note": ""}]))
        zoom = ('if (window.__tgLoads === 2) {\n'
                ' var box = document.getElementById("graph"), r = box.getBoundingClientRect();\n'
                ' box.dispatchEvent(new WheelEvent("wheel", {deltaY: -400, clientX: r.left + 40,\n'
                '   clientY: r.top + 40, bubbles: true, cancelable: true}));\n'
                ' document.body.setAttribute("data-vb",\n'
                '   box.querySelector("svg").getAttribute("viewBox"));\n'
                '}\n')
        data_js = _fixture_reload(first, json.dumps(later, ensure_ascii=False))
        data_js = data_js.replace("\nwindow.TASKGRAPH", "\n" + zoom + "window.TASKGRAPH", 1)
        dom = self._open(data_js, "?poll=500", budget_ms=3000)
        self.assertEqual(dom.err_text(), "")
        body = dom.first("body")
        self.assertEqual(body.get("data-rev"), "2")
        self.assertEqual(len(dom.nodes()), 5)
        self.assertTrue(body.get("data-vb"))
        graph_svg = next(a for t, a in dom.tags if t == "svg" and "mark" not in _classes(a))
        self.assertEqual(graph_svg.get("viewbox"), body.get("data-vb"))

    def test_page_keeps_data_when_reload_fails(self):
        # Later runs of the data script throw, as a half-written file would:
        # the old data stays and no error is shown.
        first = make_graph()
        first["task"]["rev"] = 1
        data_js = _fixture_reload(first, '(function () { throw new Error("half-written"); })()')
        dom = self._open(data_js, "?poll=500", budget_ms=3000)
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "1")
        self.assertEqual(sorted(dom.nodes()), ["1", "2", "3", "4"])

    def test_page_unsafe_links_and_hostile_title(self):
        g = make_graph()
        g["task"]["links"] = [{"label": "bad-task-link", "href": "javascript:alert(1)"},
                              {"label": "good-task-link", "href": "https://example.com/t"}]
        g["task"]["title"] = '<img src=x onerror=alert(2)>'
        item = g["items"][2]
        item["title"] = '<img src=x onerror=alert(3)>'
        item["links"] = [{"label": "bad-item-link", "href": " JaVa\tScript:alert(4)"},
                         {"label": "data-link", "href": "data:text/html,x"},
                         {"label": "mail-link", "href": "mailto:a@b.c"}]
        item["files"] = ["vbscript:msgbox(5)", "notes/readme.md"]
        dom = self._open_graph(g, "#3")
        self.assertEqual(dom.err_text(), "")
        self.assertIsNone(dom.first("img"))
        self.assertIn("<img src=x onerror=alert(3)>", dom.text)
        hrefs = [a.get("href", "") for t, a in dom.tags if t == "a"]
        self.assertFalse([h for h in hrefs if "script" in h.lower() or h.startswith("data:")],
                         hrefs)
        self.assertIn("https://example.com/t", hrefs)
        self.assertIn("mailto:a@b.c", hrefs)
        self.assertIn("notes/readme.md", hrefs)
        for label in ("bad-task-link", "bad-item-link", "data-link", "vbscript:msgbox(5)"):
            self.assertIn(label, dom.text)

    def test_page_empty_graph(self):
        dom = self._open_graph(model.new_graph("K", "T", "ru"))
        self.assertEqual(dom.nodes(), {})
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "0")
        self.assertIn("Пунктов пока нет", dom.text)


if __name__ == "__main__":
    unittest.main()
