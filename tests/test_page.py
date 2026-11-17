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

    def _fan_in_graph(self) -> dict:
        # Ten sources, three middle items and one wide sink that needs every source, as on a real
        # release graph. The data order is scrambled on purpose: the page has to find a good order.
        g = model.new_graph("K", "T", lang="en")
        src = ["S%d" % i for i in range(10)]
        g["items"] = [_item(s, []) for s in src]
        g["items"] += [_item("M1", [{"id": "S9", "note": ""}, {"id": "S0", "note": ""}]),
                       _item("M2", [{"id": "S1", "note": ""}, {"id": "S8", "note": ""}]),
                       _item("M3", [{"id": "S2", "note": ""}, {"id": "S7", "note": ""}]),
                       _item("SINK", [{"id": s, "note": ""} for s in src])]
        return g

    def _segments(self, dom: _Dom) -> list:
        """(edge index, horizontal?, fixed coordinate, low, high) for every straight piece of every arrow."""
        out = []
        paths = [a for t, a in dom.tags if t == "path" and "edge" in _classes(a)]
        for k, a in enumerate(paths):
            pts = []
            for cmd in a["d"].replace("M", "|M").replace("L", "|L").replace("Q", "|Q").split("|")[1:]:
                nums = [float(n) for n in cmd[1:].replace(",", " ").split()]
                pts.append((cmd[0], nums[-2], nums[-1]))
            for (c0, x0, y0), (c1, x1, y1) in zip(pts, pts[1:]):
                if c1 != "L" or (x0, y0) == (x1, y1):
                    continue
                if y0 == y1:
                    out.append((k, True, y0, min(x0, x1), max(x0, x1)))
                elif x0 == x1:
                    out.append((k, False, x0, min(y0, y1), max(y0, y1)))
        return out

    def test_page_wide_sink_arrows_keep_apart(self):
        # Every arrow gets its own port and its own track: no two arrows share a piece of line, and the
        # ten arrowheads on the sink stay at least 12 px apart.
        for layout in ("lr", "tb"):
            dom = self._open_graph(self._fan_in_graph(), "?dir=" + layout)
            self.assertEqual(dom.err_text(), "")
            segs = self._segments(dom)
            for i, s in enumerate(segs):
                for t in segs[i + 1:]:
                    if s[0] != t[0] and s[1] == t[1] and abs(s[2] - t[2]) < 0.5:
                        self.assertLessEqual(min(s[4], t[4]) - max(s[3], t[3]), 0.5, (layout, s, t))
            ends = []
            for t, a in dom.tags:
                if t == "path" and "edge" in _classes(a) and a.get("data-b") == "SINK":
                    x, y = a["d"].split("L")[-1].split(",")
                    ends.append(float(y) if layout == "lr" else float(x))
            self.assertEqual(len(ends), 10)
            ends.sort()
            self.assertGreaterEqual(min(b - a for a, b in zip(ends, ends[1:])), 12, (layout, ends))

    def test_page_orders_layers_to_avoid_crossings(self):
        # Two layers of a real release graph: a smoke test (N2) needs all ten items of the first layer, and
        # three more items need overlapping sets of them. Some crossings cannot be avoided (the best order
        # has 20); sorting by neighbours alone stops at 40, the search must get close to the minimum.
        needs = {"I12": ["I1", "N4"], "I3": ["I10", "I8", "I4"], "N1": ["I8", "I10"],
                 "I2": ["I6", "I8", "I10", "I4", "N6"],
                 "N2": ["I1", "I4", "I5", "I6", "I8", "I10", "N3", "N4", "N5", "N6"]}
        g = model.new_graph("K", "T", lang="en")
        g["items"] = [_item(s, []) for s in ("I1", "I4", "I10", "I5", "I8", "I6", "N3", "N4", "N5", "N6")]
        g["items"] += [_item(b, [{"id": a, "note": ""} for a in deps]) for b, deps in needs.items()]
        for layout in ("lr", "tb"):
            dom = self._open_graph(g, "?dir=" + layout)
            self.assertEqual(dom.err_text(), "")
            crossings = int(dom.first("div", id="graph").get("data-crossings"))
            self.assertLessEqual(crossings, 22, layout)

    def test_page_conflict_line_only_for_selected_item(self):
        # A conflict shows as a mark on both items; its line is hidden until one of them is selected.
        g = make_graph()
        g["conflicts"] = [{"a": "3", "b": "2", "why": "both edit one file"}]
        plain = self._open_graph(g, "?lang=en")
        group = plain.first("g", **{"class": "cfl"})
        self.assertIsNotNone(group)
        marks = [a for t, a in plain.tags if t == "tspan" and "cfmark" in _classes(a)]
        self.assertEqual(len(marks), 2)
        selected = self._open_graph(g, "?lang=en#3")
        self.assertIsNotNone(selected.first("g", **{"class": "cfl on"}))
        other = self._open_graph(g, "?lang=en#1")
        self.assertIsNone(other.first("g", **{"class": "cfl on"}))

    def test_page_states(self):
        nodes = self._open_graph(make_graph()).nodes()
        self.assertIn("st-ready", nodes["3"])
        self.assertIn("st-blocked", nodes["4"])
        self.assertIn("st-wait-me", nodes["2"])
        self.assertIn("st-done", nodes["1"])

    def test_page_review_status(self):
        g = make_graph()
        g["items"][2]["status"] = "review"
        dom = self._open_graph(g, "?lang=ru")
        self.assertIn("st-review", dom.nodes()["3"])
        self.assertIn("На ревью", dom.text)
        self.assertIn("ждут ревью или мерджа", dom.text)
        self.assertEqual(dom.err_text(), "")
        en = self._open_graph(g, "?lang=en")
        self.assertIn("In review", en.text)
        self.assertIn("waiting for review or merge", en.text)
        self.assertEqual(en.err_text(), "")

    def _session_badges(self, dom: _Dom) -> list[str]:
        start = next(i for i, (t, a) in enumerate(dom.tags) if a.get("id") == "sessions")
        badges = [c for t, a in dom.tags[start + 1:] if t == "span" and "badge" in _classes(a)
                  for c in _classes(a) if c.startswith("b-")]
        return badges[:2]  # the two sessions of make_graph() come first

    def test_page_session_state_follows_items(self):
        g = make_graph()
        g["sessions"][0]["state"] = "done"  # stale hand-set value is ignored
        self.assertEqual(self._session_badges(self._open_graph(g)), ["b-todo", "b-wait-me"])
        g["items"][2]["status"] = "doing"
        g["items"][1]["status"] = "done"
        self.assertEqual(self._session_badges(self._open_graph(g)), ["b-doing", "b-todo"])
        g["items"][2]["status"] = "done"
        g["items"][3]["status"] = "review"
        self.assertEqual(self._session_badges(self._open_graph(g)), ["b-done", "b-review"])

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

    def test_page_wait_count_in_tab_title_and_favicon(self):
        # make_graph has one item waiting on the user (2).
        dom = self._open_graph(make_graph(), "?lang=en")
        self.assertIn("(1) Task map K-1 · Flagman", dom.text)
        self.assertIn("%3Ccircle", dom.first("link", rel="icon")["href"])
        self.assertEqual(dom.err_text(), "")

        g = make_graph()
        g["items"][2]["status"] = "wait-me"
        self.assertIn("(2) Task map K-1 · Flagman", self._open_graph(g, "?lang=en").text)

        g["items"][1]["status"] = "doing"
        g["items"][2]["status"] = "doing"
        quiet = self._open_graph(g, "?lang=en")
        self.assertNotIn("(", quiet.text.split("Flagman")[0])
        self.assertIn("Task map K-1 · Flagman", quiet.text)
        self.assertNotIn("%3Ccircle", quiet.first("link", rel="icon")["href"])

    def test_page_wait_count_follows_reload(self):
        first = make_graph()
        first["task"]["rev"] = 1
        later = make_graph()
        later["task"]["rev"] = 2
        later["items"][2]["status"] = "wait-me"
        dom = self._open(_fixture_reload(first, json.dumps(later, ensure_ascii=False)),
                         "?poll=500&lang=en", budget_ms=4000)
        self.assertEqual(dom.first("body").get("data-rev"), "2")
        self.assertIn("(2) Task map K-1 · Flagman", dom.text)

    # A stand-in for the browser's Notification that records the last one in body[data-note],
    # and a page that is not focused, as in a background tab.
    FAKE_NOTIFY = ("window.Notification = function (t, o) {"
                   " document.body.setAttribute('data-note', t + '|' + o.body); };\n"
                   "window.Notification.permission = 'granted';\n"
                   "window.Notification.requestPermission = function () {"
                   " return Promise.resolve('granted'); };\n"
                   "document.hasFocus = function () { return false; };\n")

    def _open_notify(self, enabled: bool) -> _Dom:
        first = make_graph()
        first["task"]["rev"] = 1
        later = make_graph()
        later["task"]["rev"] = 2
        later["items"][2]["status"] = "wait-me"
        later["items"][2]["wait"] = "pick a name"
        pref = "localStorage.setItem('fm-notify', '%s');\n" % ("1" if enabled else "0")
        data_js = (self.FAKE_NOTIFY + pref
                   + _fixture_reload(first, json.dumps(later, ensure_ascii=False)))
        return self._open(data_js, "?poll=500&lang=en", budget_ms=4000)

    def test_page_notifies_when_an_item_newly_waits(self):
        dom = self._open_notify(True)
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "2")
        # Only item 3 is new: item 2 already waited at the first render, which never notifies.
        self.assertEqual(dom.first("body").get("data-note"),
                         "Waiting on you · K-1 · Flagman|3 · Item 3 — pick a name")
        self.assertIn("on", _classes(dom.first("button", id="notify")))

    def test_page_notifications_off_by_default(self):
        dom = self._open_notify(False)
        self.assertEqual(dom.first("body").get("data-rev"), "2")
        self.assertIsNone(dom.first("body").get("data-note"))
        button = dom.first("button", id="notify")
        self.assertNotIn("on", _classes(button))
        self.assertNotIn("hidden", button)

    def test_page_empty_graph(self):
        dom = self._open_graph(model.new_graph("K", "T", "ru"))
        self.assertEqual(dom.nodes(), {})
        self.assertEqual(dom.err_text(), "")
        self.assertEqual(dom.first("body").get("data-rev"), "0")
        self.assertIn("Пунктов пока нет", dom.text)


if __name__ == "__main__":
    unittest.main()
