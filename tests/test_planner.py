"""Planner tests: plans for trips not booked yet. Run: python3 -m unittest discover -s tests"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
CP = ROOT / "plugins" / "wayfare-claude"
FX = ROOT / "tests" / "fixtures" / "planner"
sys.path.insert(0, str(CP / "scripts"))
import planner as P  # noqa: E402

PLAN = json.loads((CP / "samples" / "plans.sample.json").read_text())["plans"][0]
DAY1 = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)


def fetch_from(folder, change=None):
    base = P.fixture_fetch(str(folder))
    calls = []

    def f(params):
        calls.append(params)
        r = copy.deepcopy(base(params))
        if change:
            change(params, r)
        return r
    f.calls = calls
    return f


def search(plan=PLAN, prev=None, now=DAY1, change=None):
    f = fetch_from(FX, change)
    rec, used = P.search_plan(plan, prev, now, f, lambda place: None)
    return rec, used, f.calls


class Validate(unittest.TestCase):
    def test_sample_is_valid(self):
        self.assertEqual(P.validate([PLAN]), [])

    def test_errors(self):
        bad = copy.deepcopy(PLAN)
        bad["id"] = "Bad Id"
        bad["travellers"]["childrenAges"] = [5, 30]
        bad["flights"]["out"]["from"] = ["Amsterdam"]
        bad["flights"]["back"]["date"] = "2027-06-01"
        bad["flights"]["back"]["arriveBefore"] = "6pm"
        bad["stay"]["checkOut"] = bad["stay"]["checkIn"]
        errs = "\n".join(P.validate([bad]))
        for word in ("id must be", "childrenAges", "IATA", "before flights.out.date", "arriveBefore", "checkOut"):
            self.assertIn(word, errs)


class Search(unittest.TestCase):
    def test_params_for_family(self):
        rec, used, calls = search()
        self.assertEqual(used, 3)
        out = next(c for c in calls if c["engine"] == "google_flights" and c["departure_id"] == "AMS")
        self.assertEqual((out["adults"], out["children"], out["flight_type"]), (2, 2, "one_way"))
        self.assertNotIn("infants_on_lap", out)
        hotel = next(c for c in calls if c["engine"] == "google_hotels")
        self.assertEqual((hotel["children_ages"], hotel["hotel_class"], hotel["free_cancellation"]), ("5,3", "4,5", "true"))
        self.assertEqual(hotel["q"], "hotels near Pueblo Mascarat, Altea")

    def test_pax_ages(self):
        p = copy.deepcopy(PLAN)
        p["travellers"] = {"adults": 1, "childrenAges": [1, 7, 13]}
        self.assertEqual(P.pax(p), {"adults": 2, "children": 1, "infants_on_lap": 1})

    def test_flight_wishes(self):
        rec, _, _ = search()
        out, back = rec["legs"]["out"], rec["legs"]["back"]
        self.assertEqual([o["flights"] for o in out["options"]], [["HV5131"], ["KL1543"]])
        self.assertEqual(out["stats"]["excluded"], {"stops": 1, "late": 1})   # one-stop Iberia, 14:05 Vueling
        self.assertEqual([o["arr"] for o in back["options"]], ["13:00", "15:40"])  # 21:55 is after 18:00
        self.assertEqual((out["cheapest"], back["cheapest"]), (620.0, 590.0))

    def test_next_day_arrival_misses_arrive_before(self):
        o = {"dep": "23:00", "arr": "01:10", "arrNextDay": True, "stops": 0, "airlines": ["X"], "flights": ["X1"]}
        self.assertEqual(P.flight_ok(o, {"arriveBefore": "18:00"}, None), (False, "late"))

    def test_stays(self):
        rec, _, _ = search()
        st = rec["stay"]
        names = [o["name"] for o in st["options"]]
        self.assertEqual(names[0], "Pueblo Mascarat Apartments")        # preferred first, kept without stars
        self.assertNotIn("Hotel Altaya", names)                         # 3 stars
        self.assertEqual(st["stats"]["excluded"], {"stars": 1})
        self.assertIsNone(st["options"][0]["link"])                     # http link dropped
        self.assertEqual(st["cheapest"], 680.0)
        self.assertEqual(rec["total"], 620 + 590 + 680)

    def test_preferred_searched_by_name_when_missing(self):
        def drop_pref(params, r):
            if params["engine"] == "google_hotels" and params["q"].startswith("hotels near"):
                r["properties"] = [h for h in r["properties"] if "Mascarat" not in h["name"]]
        rec, used, calls = search(change=drop_pref)
        named = [c for c in calls if c["engine"] == "google_hotels" and c["q"] == "Pueblo Mascarat"]
        self.assertEqual(len(named), 1)
        self.assertNotIn("hotel_class", named[0])
        self.assertEqual(used, 4)

    def test_booked_parts_are_not_searched(self):
        p = copy.deepcopy(PLAN)
        p["booked"] = {"out": "f1", "stay": "h1"}
        rec, used, calls = search(plan=p)
        self.assertEqual(used, 1)
        self.assertEqual(list(rec["legs"]), ["back"])
        self.assertIsNone(rec["stay"])
        self.assertEqual(rec["total"], 590.0)


class Alerts(unittest.TestCase):
    def day2(self, change):
        rec1, _, _ = search()
        rec2, _, _ = search(prev=rec1, now=DAY2, change=change)
        return rec2, P.plan_alerts(PLAN, rec2)

    def test_no_alert_on_first_check(self):
        rec, _, _ = search()
        self.assertEqual(P.plan_alerts(PLAN, rec), [])

    def test_flight_drop(self):
        def cheaper(params, r):
            if params.get("departure_id") == "AMS":
                r["best_flights"][0]["price"] = 540
        rec, al = self.day2(cheaper)
        self.assertEqual([a["kind"] for a in al], ["plan_flight_drop"])
        self.assertIn("now EUR 540, was EUR 620", al[0]["detail"])
        self.assertIn("lowest price", al[0]["detail"])
        self.assertTrue(al[0]["link"].startswith("https://www.google.com/travel/flights"))
        self.assertEqual(rec["history"]["out"], [["2026-10-19", 620.0], ["2026-10-22", 540.0]])

    def test_small_drop_is_quiet(self):
        def bit(params, r):
            if params.get("departure_id") == "AMS":
                r["best_flights"][0]["price"] = 605          # 15 < minDropAmount 20
        self.assertEqual(self.day2(bit)[1], [])

    def test_preferred_drop_once(self):
        def pref(params, r):
            if params["engine"] == "google_hotels":
                r["properties"][3]["total_price"]["extracted_lowest"] = 600
        _, al = self.day2(pref)
        self.assertEqual([a["kind"] for a in al], ["plan_pref_drop"])   # not also plan_stay_drop

    def test_no_matching_flights(self):
        def late(params, r):
            if params.get("departure_id") == "ALC":
                for g in ("best_flights", "other_flights"):
                    for o in r.get(g, []):
                        o["flights"][-1]["arrival_airport"]["time"] = "20:30"
        rec, _, _ = search(change=late)
        al = P.plan_alerts(PLAN, rec)
        self.assertEqual([a["kind"] for a in al], ["plan_no_flights"])
        self.assertIn("3 flights found", al[0]["detail"])
        self.assertIsNone(rec["total"])

    def test_same_day_recheck_compares_with_earlier_day(self):
        rec1, _, _ = search()
        rec2, _, _ = search(prev=rec1, now=DAY1.replace(hour=20))
        self.assertEqual(rec2["history"]["out"], [["2026-10-19", 620.0]])
        self.assertEqual(P.plan_alerts(PLAN, rec2), [])


class Due(unittest.TestCase):
    def test_cadence(self):
        rec, _, _ = search()
        self.assertTrue(P.due(PLAN, None, DAY1, None))
        self.assertFalse(P.due(PLAN, rec, DAY1.replace(day=21), None))   # > 60 days away: every 3 days
        self.assertTrue(P.due(PLAN, rec, DAY2, None))
        self.assertTrue(P.due(PLAN, rec, DAY1, 0))
        paused = dict(PLAN, status="paused")
        self.assertFalse(P.due(paused, None, DAY1, 0))
        past = datetime(2027, 6, 14, tzinfo=timezone.utc)
        self.assertFalse(P.due(PLAN, rec, past, 0))


class Reconcile(unittest.TestCase):
    def test_booked(self):
        plans = [copy.deepcopy(PLAN)]
        bookings = [
            {"id": "f1", "type": "flight", "from": "AMS", "to": "ALC", "depart": "2027-06-10T06:45:00+02:00"},
            {"id": "f2", "type": "flight", "from": "ALC", "to": "AMS", "depart": "2027-06-13T10:15:00+02:00", "status": "cancelled"},
            {"id": "h1", "type": "hotel", "checkIn": "2027-06-10", "checkOut": "2027-06-13", "name": "Cap Negret", "city": "Altea"},
        ]
        notes = P.reconcile(plans, bookings)
        self.assertEqual(plans[0]["booked"], {"out": "f1", "stay": "h1"})
        self.assertEqual(plans[0]["status"], "watching")
        self.assertEqual(len(notes), 2)
        bookings[1].pop("status")
        P.reconcile(plans, bookings)
        self.assertEqual(plans[0]["status"], "booked")


class Links(unittest.TestCase):
    def test_booking_url(self):
        q = parse_qs(urlparse(P.booking_url(PLAN)).query)
        self.assertEqual(q["age"], ["5", "3"])
        self.assertEqual((q["group_adults"], q["group_children"]), (["2"], ["2"]))
        self.assertEqual(q["nflt"], ["class=4;class=5"])

    def test_flights_url(self):
        q = parse_qs(urlparse(P.google_flights_url(PLAN, "back")).query)["q"][0]
        self.assertIn("ALC to AMS on 2027-06-13", q)
        self.assertIn("2 children", q)


class Build(unittest.TestCase):
    def test_build_and_page(self):
        rec, _, _ = search()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "plans.json").write_text(json.dumps({"plans": [PLAN]}))
            (d / "prices.json").write_text(json.dumps({"results": {PLAN["id"]: rec}}))
            (d / "agent.json").write_text(json.dumps({"triggerId": "trig_x"}))
            r = subprocess.run([sys.executable, str(CP / "scripts" / "planner.py"), "build", "--plans", str(d / "plans.json"),
                                "--prices", str(d / "prices.json"), "--agent", str(d / "agent.json"),
                                "--now", "2026-10-19T09:00:00+00:00", "--out-dir", str(d / "out")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            res = json.loads((d / "out" / "plans-result.json").read_text())
            self.assertEqual(len(res["newPlans"]), 1)
            page = Path(res["newPlans"][0]["page"]).read_text()
            self.assertIn("<title>Wedding in Teulada · plan</title>", page)
            batch = json.loads(Path(res["plans"][0]["batch"]).read_text())
            self.assertEqual([(w["collection"], w["doc_id"]) for w in batch], [("plan", "data"), ("private", "data")])
            data = json.loads(Path(batch[0]["file_path"]).read_text())
            self.assertEqual(data["total"], 1890.0)
            self.assertEqual([L["key"] for L in data["legs"]], ["out", "back"])
            self.assertIn("leave 06:00–12:00", data["legs"][0]["wishes"])
            self.assertNotIn("trig_x", json.dumps(data))        # trigger id only in private/data
            home = json.loads((d / "out" / "home-plans" / "batch.json").read_text())
            self.assertEqual([w["doc_id"] for w in home], ["plans", "plans", "planprices"])
            caps = json.loads((d / "out" / "capabilities-plan.json").read_text())
            self.assertIn({"path": "private", "read": "owner", "write": "owner"}, caps["db"]["rules"])



class SearchErrors(unittest.TestCase):
    def test_error_is_kept_and_shown(self):
        import urllib.error
        rec, _, _ = search()

        def boom(params):
            raise urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        orig = P.searchapi_get
        P.searchapi_get = boom
        try:
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / "plans.json").write_text(json.dumps({"plans": [PLAN]}))
                (d / "prev.json").write_text(json.dumps({"results": {PLAN["id"]: rec}}))
                P.main(["search", "--plans", str(d / "plans.json"), "--previous", str(d / "prev.json"),
                        "--out", str(d / "out.json"), "--every-hours", "0", "--now", "2026-10-22T08:00:00+00:00"])
                out = json.loads((d / "out.json").read_text())[PLAN["id"]]
        finally:
            P.searchapi_get = orig
        self.assertIn("does not allow www.searchapi.io", out["lastError"])
        self.assertEqual(out["total"], rec["total"])                       # last good prices stay
        page = P.plan_page(PLAN, out, DAY2)
        self.assertIn("does not allow", page["error"])
        self.assertIsNone(P.plan_page(PLAN, rec, DAY2)["error"])

    def test_first_check_fails(self):
        rec = {"planId": PLAN["id"], "history": {}, "lastError": "blocked", "lastErrorAt": DAY1.isoformat()}
        page = P.plan_page(PLAN, rec, DAY1)
        self.assertEqual((page["error"], page["total"], page["alerts"]), ("blocked", None, []))


if __name__ == "__main__":
    unittest.main()
