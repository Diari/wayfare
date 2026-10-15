"""Run: python3 -m unittest discover -s tests -v"""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import wayfare  # noqa: E402
import fare_check  # noqa: E402

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
SAMPLE = json.loads((ROOT / "samples" / "bookings.sample.json").read_text())
PROFILE = json.loads((ROOT / "samples" / "profile.sample.json").read_text())


def build(bookings, profile=PROFILE, fares=None, **kw):
    return wayfare.build(bookings, profile, fares or [], NOW, **kw)


def trips(r):
    return [t["public"] for t in r["trips"]]


def kinds(trip, open_only=False):
    return [a["kind"] for a in trip["alerts"] if not (open_only and a.get("resolution"))]


class Validation(unittest.TestCase):
    def test_sample_is_valid(self):
        self.assertEqual(wayfare.validate(SAMPLE), [])

    def test_time_without_offset_is_rejected(self):
        b = copy.deepcopy(SAMPLE[0]); b["depart"] = "2026-11-06T16:55:00"
        self.assertTrue(any("no UTC offset" in e for e in wayfare.validate([b])))

    def test_bad_airport_dates_and_link(self):
        b = copy.deepcopy(SAMPLE[0]); b["from"] = "Amsterdam"; b["manageUrl"] = "javascript:alert(1)"
        h = copy.deepcopy(SAMPLE[1]); h["checkOut"] = h["checkIn"]
        errs = wayfare.validate([b, h])
        self.assertTrue(any("IATA" in e for e in errs))
        self.assertTrue(any("checkOut must be after" in e for e in errs))
        self.assertTrue(any("manageUrl" in e for e in errs))

    def test_duplicate_ids(self):
        self.assertTrue(any("duplicate" in e for e in wayfare.validate([SAMPLE[1], SAMPLE[1]])))


class Trips(unittest.TestCase):
    def setUp(self):
        self.r = build(SAMPLE)
        self.lis, self.ber = trips(self.r)

    def test_two_trips_grouped_by_home(self):
        self.assertEqual([t["slug"] for t in trips(self.r)], ["lisbon-2026-11", "berlin-2026-12"])
        self.assertEqual(self.lis["title"], "Lisbon & Porto")
        self.assertEqual(self.lis["pageTitle"], "Lisbon & Porto, Nov 2026")
        self.assertEqual(self.ber["title"], "Berlin")  # Frankfurt is only a connection
        self.assertTrue(all(t["isNew"] for t in self.r["trips"]))

    def test_lodging_gap_in_porto(self):
        g = self.lis["gaps"][0]
        self.assertEqual((g["city"], g["firstNight"], g["lastNight"], g["nights"]), ("Porto", "2026-11-10", "2026-11-11", 2))
        self.assertEqual(self.ber["gaps"], [])

    def test_schedule_change_ripples_to_dinner(self):
        self.assertIn("schedule_change", kinds(self.lis))
        dining = next(a for a in self.lis["alerts"] if a["kind"] == "tight_dining")
        self.assertTrue(dining.get("fromChange"))
        self.assertIn("40 min", dining["title"])

    def test_tight_connection(self):
        a = next(a for a in self.ber["alerts"] if a["kind"] == "tight_connection")
        self.assertIn("35 min", a["title"])

    def test_timeline_puts_hotel_after_arrival(self):
        titles = [i["title"] for i in self.lis["items"]]
        self.assertLess(titles.index("Amsterdam → Lisbon"), titles.index("Casa do Largo (sample)"))
        self.assertLess(titles.index("Casa do Largo (sample)"), titles.index("Taberna Azul (sample)"))

    def test_no_show_when_flight_moves_to_next_day(self):
        b = copy.deepcopy(SAMPLE)
        b[0]["depart"] = "2026-11-07T07:05:00+01:00"; b[0]["arrive"] = "2026-11-07T09:00:00+00:00"
        self.assertIn("no_show_risk", kinds(trips(build(b))[0]))

    def test_late_checkin(self):
        b = copy.deepcopy(SAMPLE)
        b[0]["depart"] = "2026-11-06T21:30:00+01:00"; b[0]["arrive"] = "2026-11-06T23:25:00+00:00"
        self.assertIn("late_checkin", kinds(trips(build(b))[0]))

    def test_double_booking(self):
        b = copy.deepcopy(SAMPLE)
        extra = copy.deepcopy(b[1]); extra["id"] = "hotel-dup"; extra["name"] = "Other Hotel"
        b.append(extra)
        self.assertIn("double_booking", kinds(trips(build(b))[0]))

    def test_cancelled_booking_reopens_gap(self):
        b = copy.deepcopy(SAMPLE); b[4]["status"] = "cancelled"   # Porto hotel
        self.assertEqual(sum(g["nights"] for g in trips(build(b))[0]["gaps"]), 4)

    def test_fare_alert_threshold(self):
        f = [{"bookingId": "flight-KL1734-2026-11-12", "paidPerTraveler": 143, "livePerTraveler": 130,
              "currency": "EUR", "checkedAt": "2026-10-15T20:00:00Z"}]
        self.assertNotIn("fare_drop", kinds(trips(build(SAMPLE, fares=f))[0]))  # 13 < 25
        f[0]["livePerTraveler"] = 109
        a = next(x for x in trips(build(SAMPLE, fares=f))[0]["alerts"] if x["kind"] == "fare_drop")
        self.assertIn("EUR 68 for 2", a["detail"])

    def test_without_home_gap_grouping(self):
        self.assertEqual(len(build(SAMPLE, profile={})["trips"]), 2)

    def test_past_trips_drop_off(self):
        r = wayfare.build(SAMPLE, PROFILE, [], datetime(2026, 11, 20, tzinfo=timezone.utc))
        self.assertEqual([t["slug"] for t in trips(r)], ["berlin-2026-12"])


class RouteAndNights(unittest.TestCase):
    def test_lisbon_route_and_nights(self):
        lis = trips(build(SAMPLE))[0]
        r = [(s["city"], s["kind"], s.get("mode"), s.get("nights"), s.get("unbooked")) for s in lis["route"]]
        self.assertEqual(r, [("Amsterdam", "start", None, None, None), ("Lisbon", "stay", "flight", 2, 0),
                             ("Porto", "stay", "train", 4, 2), ("Amsterdam", "end", "flight", None, None)])
        kinds_ = [n["kind"] for n in lis["nights"]]
        self.assertEqual(kinds_, ["stay", "stay", "stay", "stay", "gap", "gap"])
        self.assertEqual(lis["nights"][4]["city"], "Porto")
        self.assertEqual(len(lis["nights"]), sum(s.get("nights", 0) for s in lis["route"]))

    def test_connection_city_not_on_route(self):
        ber = trips(build(SAMPLE))[1]
        self.assertEqual([s["city"] for s in ber["route"]], ["Amsterdam", "Berlin", "Amsterdam"])

    def test_typed_fields(self):
        items = {i["id"]: i for i in trips(build(SAMPLE))[0]["items"]}
        f = items["flight-TP669-2026-11-06"]
        self.assertEqual((f["fromCode"], f["toCode"], f["number"]), ("AMS", "LIS", "TP 669"))
        self.assertEqual(items["hotel-casa-do-largo-2026-11-06"]["nights"], 2)
        self.assertEqual(items["dining-taberna-azul-2026-11-06"]["party"], 2)
        self.assertEqual(items["train-lis-opo-2026-11-08"]["fromName"], "Lisboa Santa Apolónia")


class AlertsAndActions(unittest.TestCase):
    def test_ids_are_stable_and_valid(self):
        a1 = {a["id"] for a in trips(build(SAMPLE))[0]["alerts"]}
        a2 = {a["id"] for a in trips(build(copy.deepcopy(SAMPLE)))[0]["alerts"]}
        self.assertEqual(a1, a2)
        for i in a1:
            self.assertRegex(i, r"^[A-Za-z0-9_\-]{1,200}$")

    def test_gap_alert_has_search_link_and_ask(self):
        gap = next(a for a in trips(build(SAMPLE))[0]["alerts"] if a["kind"] == "lodging_gap")
        self.assertIn("checkin=2026-11-10", gap["links"][0]["url"])
        self.assertIn("checkout=2026-11-12", gap["links"][0]["url"])
        self.assertEqual(gap["ask"]["kind"], "find-stays")
        self.assertEqual(gap["ask"]["guests"], 2)

    def test_action_hides_alert_until_facts_change(self):
        lis = trips(build(SAMPLE))[0]
        gap = next(a for a in lis["alerts"] if a["kind"] == "lodging_gap")
        acts = {"lisbon-2026-11": {gap["id"]: {"alertId": gap["id"], "fingerprint": gap["fingerprint"], "status": "ignored"}}}
        lis2 = trips(build(SAMPLE, actions=acts))[0]
        self.assertNotIn("lodging_gap", kinds(lis2, open_only=True))
        self.assertEqual(lis2["counts"]["handled"], 1)
        # Porto hotel cancelled: the gap grows, so the old "ignored" no longer applies
        b = copy.deepcopy(SAMPLE); b[4]["status"] = "cancelled"
        self.assertIn("lodging_gap", kinds(trips(build(b, actions=acts))[0], open_only=True))

    def test_snooze_expires(self):
        lis = trips(build(SAMPLE))[0]
        a = lis["alerts"][0]
        later = (NOW + timedelta(days=3)).isoformat()
        acts = {"lisbon-2026-11": {a["id"]: {"fingerprint": a["fingerprint"], "status": "snoozed", "until": later}}}
        self.assertEqual(trips(build(SAMPLE, actions=acts))[0]["counts"]["handled"], 1)
        r = wayfare.build(SAMPLE, PROFILE, [], NOW + timedelta(days=4), actions=acts)
        self.assertEqual(trips(r)[0]["counts"]["handled"], 0)


class Matching(unittest.TestCase):
    def test_trip_keeps_its_page_when_it_grows(self):
        r1 = build(SAMPLE)
        index = [dict(t["index"], url=f"https://claude.ai/artifact/{t['slug']}") for t in r1["trips"]]
        # extend the Porto stay: now Porto has most nights, so the "city" changes
        b = copy.deepcopy(SAMPLE); b[4]["checkOut"] = "2026-11-12"
        r2 = build(b, index=index)
        lis = r2["trips"][0]
        self.assertEqual(lis["slug"], "lisbon-2026-11")
        self.assertFalse(lis["isNew"])
        self.assertEqual(lis["public"]["pageTitle"], "Lisbon & Porto, Nov 2026")
        self.assertEqual(lis["url"], "https://claude.ai/artifact/lisbon-2026-11")

    def test_fully_cancelled_trip_is_marked(self):
        r1 = build(SAMPLE)
        index = [dict(t["index"], url="https://x/" + t["slug"]) for t in r1["trips"]]
        b = copy.deepcopy(SAMPLE)
        for x in b[6:]:
            x["status"] = "cancelled"
        r2 = build(b, index=index)
        self.assertEqual([e["status"] for e in r2["leftovers"]], ["cancelled"])


class SampleRetire(unittest.TestCase):
    def test_sample_pages_retire_on_first_real_sync(self):
        rs = build(SAMPLE, sample=True)
        index = [dict(t["index"], url="https://x/" + t["slug"]) for t in rs["trips"]]
        real = copy.deepcopy(SAMPLE[6:8])
        for b in real:
            b["id"] += "-real"; b["confirmation"] = "REAL" + b["confirmation"]
        r = build(real, index=index)
        self.assertEqual(sorted(e["status"] for e in r["leftovers"]), ["sample", "sample"])
        self.assertTrue(r["trips"][0]["isNew"])
        self.assertNotIn(r["trips"][0]["slug"], {e["slug"] for e in index})


class Privacy(unittest.TestCase):
    def test_shared_docs_have_no_codes_prices_or_manage_links(self):
        b = copy.deepcopy(SAMPLE); b[0]["manageUrl"] = "https://www.flytap.com/manage?token=SECRET123"
        r = build(b)
        public = json.dumps([t["public"] for t in r["trips"]] + [t["index"] for t in r["trips"]])
        for x in b:
            self.assertNotIn(x["confirmation"], public)
        self.assertNotIn('"price"', public)
        self.assertNotIn("SECRET123", public)
        private = json.dumps(r["trips"][0]["private"])
        self.assertIn("SECRET123", private)
        self.assertIn("QZ7XKM", private)

    def test_mask(self):
        self.assertEqual(wayfare.mask_code("QZ7XKM"), "••••KM")
        self.assertIsNone(wayfare.mask_code(None))


class Outputs(unittest.TestCase):
    def test_plan_batches_and_home(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            r = build(SAMPLE, agent={"triggerId": "trig_test"})
            versions = {"home": {"index/trips": 4}, "trips": {}}
            plan = wayfare.write_outputs(r, out, versions, ROOT / "dashboard" / "trip.html")
            self.assertEqual(len(plan["newTrips"]), 2)
            page = Path(plan["newTrips"][0]["page"]).read_text()
            self.assertIn("<title>Lisbon &amp; Porto, Nov 2026</title>", page)
            batch = json.loads(Path(plan["trips"][0]["batch"]).read_text())
            self.assertEqual([(w["collection"], w["doc_id"]) for w in batch], [("trip", "data"), ("private", "data")])
            priv = json.loads(Path(batch[1]["file_path"]).read_text())
            self.assertEqual(priv["agent"]["triggerId"], "trig_test")
            with self.assertRaises(SystemExit):
                wayfare.home_batch(out, {})
            hb = json.loads(wayfare.home_batch(out, {"lisbon-2026-11": "u1", "berlin-2026-12": "u2"}).read_text())
            self.assertEqual(hb[0]["if_version"], 4)
            idx = json.loads(Path(hb[0]["file_path"]).read_text())
            self.assertEqual([e["url"] for e in idx["trips"]], ["u1", "u2"])
            self.assertEqual(hb[1]["doc_id"], "bookings")

    def test_sample_never_writes_bookings(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            wayfare.write_outputs(build(SAMPLE, sample=True), out, {}, ROOT / "dashboard" / "trip.html")
            hb = json.loads(wayfare.home_batch(out, {"lisbon-2026-11": "u1", "berlin-2026-12": "u2"}).read_text())
            self.assertEqual([w["doc_id"] for w in hb], ["trips"])

    def test_actions_loaded_from_saved_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "lisbon-2026-11" / "actions"; p.mkdir(parents=True)
            (p / "lodging_gap-abc.json").write_text(json.dumps({"fingerprint": "f", "status": "done"}))
            acts = wayfare.load_actions(d)
            self.assertEqual(acts["lisbon-2026-11"]["lodging_gap-abc"]["status"], "done")


class Merge(unittest.TestCase):
    def test_schedule_change_email_updates_original(self):
        old = copy.deepcopy(SAMPLE[5])
        new = {k: old[k] for k in ("type", "carrier", "flightNumber", "from", "to", "fromCity", "toCity", "confirmation")}
        new.update({"id": "flight-KL1734-2026-11-13", "depart": "2026-11-13T07:00:00+00:00",
                    "arrive": "2026-11-13T10:45:00+01:00"})
        merged, notes = wayfare.merge([old], [new])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "changed")
        self.assertEqual(merged[0]["previous"]["depart"], old["depart"])
        self.assertEqual(merged[0]["price"], old["price"])

    def test_new_booking_added_and_cancel(self):
        cancel = {"id": SAMPLE[1]["id"], "type": "hotel", "status": "cancelled", "name": SAMPLE[1]["name"],
                  "city": "Lisbon", "checkIn": "2026-11-06", "checkOut": "2026-11-08", "confirmation": SAMPLE[1]["confirmation"]}
        merged, _ = wayfare.merge(SAMPLE[:2], [cancel, SAMPLE[2]])
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[1]["status"], "cancelled")


class Fares(unittest.TestCase):
    def offer(self, carrier="KL", number="1734", dep="2026-11-12T12:10:00", amount="230.00", segs=1):
        seg = {"marketing_carrier": {"iata_code": carrier}, "marketing_carrier_flight_number": number, "departing_at": dep}
        return {"id": "off_1", "total_amount": amount, "total_currency": "EUR", "slices": [{"segments": [seg] * segs}]}

    def test_match_same_flight_cheapest(self):
        resp = {"data": {"offers": [self.offer(amount="260.00"), self.offer(amount="230.00"),
                                    self.offer(number="1736", amount="90.00"), self.offer(segs=2, amount="80.00")]}}
        self.assertEqual(fare_check.best_matching_offer(SAMPLE[5], resp)["amount"], 230.0)

    def test_candidates_skip_connections(self):
        check, skipped = fare_check.candidates(SAMPLE, NOW)
        self.assertIn("flight-KL1734-2026-11-12", [b["id"] for b in check])
        self.assertTrue(any(s["bookingId"] == "flight-LH179-2026-12-06" for s in skipped))


if __name__ == "__main__":
    unittest.main()
