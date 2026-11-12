import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import detect, http, pagewatch, tracker
from hutwatch.extract import extract


def sentences(html):
    return extract(html).sentences


class FakeNotifier:
    def __init__(self):
        self.issues, self.errors, self.repo = [], [], "me/repo"
        self.ntfy_topic, self.tg_token, self.tg_chat = "", "", ""

    def issue(self, title, body, comment_only=False):
        self.issues.append((title, body, comment_only))

    def telegram(self, text):
        pass

    def ntfy(self, *a, **k):
        pass


class OpenDetection(unittest.TestCase):
    # Positive controls: must fire.
    def test_positive_italian(self):
        self.assertTrue(detect.open_matches(sentences("<p>Prenotazioni aperte per la stagione 2027!</p>")))

    def test_positive_site_update(self):
        html = "<p>Apertura/Open : Sabato 5 giugno 2027 / Saturday 5th June 2027</p>"
        self.assertTrue(detect.open_matches(sentences(html)))

    def test_positive_english(self):
        self.assertTrue(detect.open_matches(sentences("<div>Bookings open for season 2027.</div>")))

    # Negative controls: must not fire.
    def test_negative_sentences(self):
        for s in [
            "Le prenotazioni per il 2027 non sono ancora aperte.",
            "Non abbiamo iniziato a prendere prenotazioni per il 2027.",
            "Bookings for 2027 are not yet open.",
            "Prenotazioni 2027: non ancora disponibili.",
            "Stagione 2027: prenotazioni aperte prossimamente.",
        ]:
            self.assertEqual(detect.open_matches(sentences(f"<p>{s}</p>")), [], s)

    def test_null_current_2026_page(self):
        html = ("<p>Apertura/Open : Sabato 6 giugno 2026 / Saturday 6th June 2026 "
                "Chiusura/Closed : Mercoledì 30 settembre 2026</p>")
        self.assertEqual(detect.open_matches(sentences(html)), [])

    def test_iso_timestamp_is_not_a_year(self):
        html = "<p>Dettaglio rifugio cai 2027-02-28T14:02:53+01:00 Prenotazione aggiunta al carrello</p>"
        self.assertEqual(detect.open_matches(sentences(html)), [])

    def test_date_with_slashes_counts(self):
        self.assertTrue(detect.open_matches(sentences("<p>Prenotabile dal 01/03/2027</p>")))


class ChangeImportance(unittest.TestCase):
    """Page-change pushes say IMPORTANT / Not important up front, and what they did."""

    def ex(self, old, new):
        return detect.explain_change(old, new)

    # Real case (Sennes contact page, 12 Nov 2026): stray "/h2>" removed.
    def test_formatting_fix_is_not_important(self):
        c = self.ex(["Attention: Use payment button only after receiving our reservation confirmation!/h2>"],
                    ["Attention: Use payment button only after receiving our reservation confirmation!"])
        self.assertFalse(c.important)
        self.assertEqual(c.label, "Not important")
        self.assertIn("Formatting fix only", c.why)
        self.assertIn("«confirmation!/h2>» → «confirmation!»", c.message())

    # Negative controls: real edits, but nothing about 2027 or bookings opening.
    def test_other_wording_is_not_important(self):
        for old, new in [
            (["Rifugio aperto da giugno a settembre."], ["Rifugio aperto da metà giugno a fine settembre."]),
            (["Orari: 8-18"], ["Nuovo menu degustazione disponibile", "Orari: 8-18"]),
            (["Season 2026: 20 June - 20 September"], ["Season 2026: 20 June - 27 September"]),
            (["Prenotazioni via email."], []),
        ]:
            c = self.ex(old, new)
            self.assertFalse(c.important, (old, new, c.why))
            self.assertIn("nothing about 2027", c.why)
            self.assertTrue(c.details)

    # Positive controls: must be IMPORTANT, with the reason.
    def test_important_changes(self):
        cases = [
            (["Apertura/Open : Sabato 6 giugno 2026"], ["Apertura/Open : Sabato 5 giugno 2027"], "mentions 2027"),
            (["Le prenotazioni per il 2027 non sono ancora aperte."], ["Prenotazioni aperte! Scriveteci."],
             "bookings are open"),
            (["Contatti"], ["Contatti", "Bookings are now open."], "bookings are open"),
            (["Season 2026 is over."], ["Bookings for next season: write to us from January."], "next season"),
            (["Bookings for 2027 are not yet open."], ["Contatti"], "'not open yet' notice was removed"),
            (["Prenotazioni dal 15 gennaio ore 9:00."], ["Prenotazioni dal 12 gennaio ore 9:00."], "booking date"),
        ]
        for old, new, why in cases:
            c = self.ex(old, new)
            self.assertTrue(c.important, (old, new, c.why))
            self.assertEqual(c.label, "IMPORTANT")
            self.assertIn(why, c.why)

    def test_edit_shows_changed_words(self):
        c = self.ex(["Apertura/Open : Sabato 6 giugno 2026"], ["Apertura/Open : Sabato 5 giugno 2027"])
        self.assertIn("«6» → «5», «2026» → «2027»", c.message())

    def test_message_is_capped(self):
        c = self.ex([], [f"Prenotazione riga {i} 2026" for i in range(12)])
        self.assertIn("(+7 more changes)", c.message())
        self.assertLessEqual(len(c.message().splitlines()), 7)


class Extraction(unittest.TestCase):
    def test_strips_scripts_styles_templates(self):
        html = """<html><head><style>.x{}</style><script>var a='prenota 2027';</script></head>
        <body><script type="text/x-handlebars-template"><div class="calendar" data-available="u">2027</div></script>
        <p>Hello   world.</p><noscript>Prenota 2027</noscript></body></html>"""
        ex = extract(html)
        self.assertEqual(ex.sentences, ["Hello world."])
        self.assertEqual(ex.widget_markers, [])

    def test_widget_markers_outside_scripts(self):
        ex = extract('<div class="calendar mb-2" data-available="https://x/api?id=1"></div>')
        self.assertIn("data-available=https://x/api?id=1", ex.widget_markers)

    def test_cp1252_fallback(self):
        body = "L’ALTA VIA, Pramperét".encode("cp1252")
        self.assertEqual(http.decode_body(body, "text/html"), "L’ALTA VIA, Pramperét")


class RunLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tmp.name) / "pages.json"
        self.pages = {p.url: "<p>Apertura/Open : Sabato 6 giugno 2026</p><p>Contatti</p>" + "x" * 60
                      for p in pagewatch.PAGES}
        self.fail = set()
        patches = [
            mock.patch.object(pagewatch, "STATE_FILE", self.state_file),
            mock.patch.object(tracker, "load_or_warn", lambda *a: []),
            mock.patch.object(pagewatch.state, "today_rome", lambda: dt.date(2026, 11, 8)),
            mock.patch.object(pagewatch.http, "request", self.fake_request),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_request(self, method, url, **kw):
        if url in self.fail:
            raise http.FetchError("HTTP 503")
        return http.Response(200, url, {"Content-Type": "text/html; charset=utf-8"}, self.pages[url].encode())

    def run_once(self):
        n = FakeNotifier()
        rc = pagewatch.run(n)
        return rc, [t for t, _, _ in n.issues], n

    def test_baseline_then_change_then_open(self):
        self.assertEqual(self.run_once()[:2], (0, []))           # baseline: silent
        self.assertEqual(self.run_once()[:2], (0, []))           # unchanged: silent
        url = "http://www.piandefontana.it/"
        self.pages[url] = "<p>Apertura/Open : Sabato 5 giugno 2027</p><p>Contatti</p>" + "x" * 60
        rc, titles, n = self.run_once()
        self.assertIn("CHANGE: Pian de Fontana page", titles)
        self.assertIn("OPEN: Pian de Fontana 2027 bookings", titles)
        body = dict((t, b) for t, b, _ in n.issues)["OPEN: Pian de Fontana 2027 bookings"]
        self.assertIn("piandefontana@livecom.it", body)
        self.assertIn("Prenotazione per il 28 giugno 2027", body)
        self.assertEqual(self.run_once()[1], [])                 # same text: no repeat alert

    def test_change_push_title_and_priority(self):
        self.run_once()
        sennes = "https://www.sennes.com/en/contact/index.php"
        pushes = []

        def run_with(html):
            self.pages[sennes] = html
            n = FakeNotifier()
            n.ntfy_topic = "t"
            n.ntfy = lambda title, msg, **k: pushes.append((title, msg, k)) or True
            pagewatch.run(n)

        base = self.pages[sennes]
        run_with("<p>Use payment button only after our reservation confirmation!/h2></p>" + base)
        pushes.clear()
        run_with("<p>Use payment button only after our reservation confirmation!</p>" + base)
        self.assertEqual(len(pushes), 1)
        title, msg, k = pushes[0]
        self.assertEqual(title, "Not important: Sennes page changed")
        self.assertEqual(k["priority"], 2)
        self.assertTrue(msg.startswith("Formatting fix only"))
        self.assertIn("Page: contact/enquiry page", msg)
        pushes.clear()
        run_with("<p>Prenotazioni 2027: scriveteci dal 10 gennaio.</p>" + base)
        title, msg, k = pushes[0]
        self.assertEqual((title, k["priority"]), ("IMPORTANT: Sennes page changed", 4))
        self.assertTrue(msg.startswith("Why: new text mentions 2027"))

    def test_open_alert_is_pushed_with_email_button(self):
        self.run_once()
        url = "http://www.piandefontana.it/"
        self.pages[url] = "<p>Prenotazioni aperte per la stagione 2027!</p><p>Contatti</p>" + "x" * 60
        n = FakeNotifier()
        n.ntfy_topic = "t"
        pushes = []
        n.ntfy = lambda title, msg, **k: pushes.append((title, msg, k)) or True
        pagewatch.run(n)
        open_push = [p for p in pushes if p[0] == "OPEN: Pian de Fontana 2027 bookings"]
        self.assertEqual(len(open_push), 1)
        title, msg, k = open_push[0]
        self.assertEqual(k["priority"], 4)
        self.assertIn("Prenotazioni aperte per la stagione 2027", msg)
        email = k["extra_actions"][0]["url"]
        self.assertTrue(email.startswith("mailto:piandefontana@livecom.it?"))
        self.assertIn("28%20giugno%202027", email)

    def test_failed_push_refires_next_run(self):
        self.run_once()
        url = "http://www.piandefontana.it/"
        self.pages[url] = "<p>Prenotazioni aperte per la stagione 2027!</p><p>Contatti</p>" + "x" * 60
        n = FakeNotifier()
        n.ntfy_topic = "t"
        n.ntfy = lambda *a, **k: False  # ntfy down
        pagewatch.run(n)
        n2 = FakeNotifier()
        n2.ntfy_topic = "t"
        got = []
        n2.ntfy = lambda title, *a, **k: got.append(title) or True
        pagewatch.run(n2)
        self.assertIn("OPEN: Pian de Fontana 2027 bookings", got)

    def test_three_failures_alert_once_then_recover(self):
        self.run_once()
        url = "https://www.rifugiosommarivaalpramperet.it/"
        self.fail.add(url)
        self.assertEqual(self.run_once()[1], [])
        self.assertEqual(self.run_once()[1], [])
        self.assertEqual(self.run_once()[1], ["FAILING: Pramperet monitor"])
        self.assertEqual(self.run_once()[1], [])                 # alerted once only
        self.fail.clear()
        rc, titles, n = self.run_once()
        self.assertEqual(titles, ["FAILING: Pramperet monitor"])
        self.assertTrue(n.issues[0][2])                          # comment-only recovery note

    def test_booked_in_tracker_stops_night(self):
        booked = [tracker.Row(dt.date(2027, 6, 28), "Rifugio Pian de Fontana", "Booked", None, None)]
        with mock.patch.object(tracker, "load_or_warn", lambda *a: booked):
            n = FakeNotifier()
            with mock.patch.object(pagewatch.http, "request", side_effect=AssertionError("fetched")):
                self.assertEqual(pagewatch.run(n), 0)

    def test_stops_after_end_date(self):
        with mock.patch.object(pagewatch.state, "today_rome", lambda: dt.date(2027, 6, 29)):
            with mock.patch.object(pagewatch.http, "request", side_effect=AssertionError("fetched")):
                self.assertEqual(pagewatch.run(FakeNotifier()), 0)
        self.assertFalse(self.state_file.exists())


if __name__ == "__main__":
    unittest.main()
