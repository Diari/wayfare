"""Run: python3 -m unittest discover -s tests -v"""
import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import wayfare  # noqa: E402
import fare_check  # noqa: E402

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
SAMPLE = json.loads((ROOT / "samples" / "bookings.sample.json").read_text())
PROFILE = json.loads((ROOT / "samples" / "profile.sample.json").read_text())


def build(bookings, profile=PROFILE, fares=None):
    return wayfare.build(bookings, profile, fares or [], NOW)


def kinds(trip):
    return [a["kind"] for a in trip["alerts"]]


class Validation(unittest.TestCase):
    def test_sample_is_valid(self):
        self.assertEqual(wayfare.validate(SAMPLE), [])

    def test_time_without_offset_is_rejected(self):
        b = copy.deepcopy(SAMPLE[0]); b["depart"] = "2026-11-06T16:55:00"
        self.assertTrue(any("no UTC offset" in e for e in wayfare.validate([b])))

    def test_bad_airport_and_dates(self):
        b = copy.deepcopy(SAMPLE[0]); b["from"] = "Amsterdam"
        h = copy.deepcopy(SAMPLE[1]); h["checkOut"] = h["checkIn"]
        errs = wayfare.validate([b, h])
        self.assertTrue(any("IATA" in e for e in errs))
        self.assertTrue(any("checkOut must be after" in e for e in errs))

    def test_duplicate_ids(self):
        self.assertTrue(any("duplicate" in e for e in wayfare.validate([SAMPLE[1], SAMPLE[1]])))


class Trips(unittest.TestCase):
    def setUp(self):
        self.r = build(SAMPLE)
        self.lis, self.ber = self.r["trips"]

    def test_two_trips_grouped_by_home(self):
        self.assertEqual([t["slug"] for t in self.r["trips"]], ["lisbon-2026-11", "berlin-2026-12"])
        self.assertEqual(self.lis["title"], "Lisbon & Porto")
        self.assertEqual(self.ber["title"], "Berlin")  # Frankfurt is only a connection

    def test_lodging_gap_in_porto(self):
        self.assertEqual(len(self.lis["gaps"]), 1)
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
        lis = build(b)["trips"][0]
        self.assertIn("no_show_risk", kinds(lis))

    def test_late_checkin(self):
        b = copy.deepcopy(SAMPLE)
        b[0]["depart"] = "2026-11-06T21:30:00+01:00"; b[0]["arrive"] = "2026-11-06T23:25:00+00:00"
        self.assertIn("late_checkin", kinds(build(b)["trips"][0]))

    def test_double_booking(self):
        b = copy.deepcopy(SAMPLE)
        extra = copy.deepcopy(b[1]); extra["id"] = "hotel-dup"; extra["name"] = "Other Hotel"
        b.append(extra)
        self.assertIn("double_booking", kinds(build(b)["trips"][0]))

    def test_cancelled_booking_reopens_gap(self):
        b = copy.deepcopy(SAMPLE); b[4]["status"] = "cancelled"   # Porto hotel
        gaps = build(b)["trips"][0]["gaps"]
        self.assertEqual(sum(g["nights"] for g in gaps), 4)

    def test_fare_alert_threshold(self):
        f = [{"bookingId": "flight-KL1734-2026-11-12", "paidPerTraveler": 143, "livePerTraveler": 130,
              "currency": "EUR", "checkedAt": "2026-10-15T20:00:00Z"}]
        self.assertNotIn("fare_drop", kinds(build(SAMPLE, fares=f)["trips"][0]))  # 13 < 25
        f[0]["livePerTraveler"] = 109
        a = next(x for x in build(SAMPLE, fares=f)["trips"][0]["alerts"] if x["kind"] == "fare_drop")
        self.assertIn("EUR 68 for 2", a["detail"])

    def test_without_home_gap_grouping(self):
        r = build(SAMPLE, profile={})
        self.assertEqual(len(r["trips"]), 2)

    def test_past_trips_drop_off(self):
        later = datetime(2026, 11, 20, tzinfo=timezone.utc)
        r = wayfare.build(SAMPLE, PROFILE, [], later)
        self.assertEqual([t["slug"] for t in r["trips"]], ["berlin-2026-12"])


class Privacy(unittest.TestCase):
    def test_shared_docs_have_no_codes_prices_or_notes(self):
        r = build(SAMPLE)
        public = json.dumps({"trips": r["trips"], "status": r["status"]})
        for b in SAMPLE:
            self.assertNotIn(b["confirmation"], public)
        self.assertNotIn('"price"', public)
        self.assertNotIn("412", public)

    def test_mask(self):
        self.assertEqual(wayfare.mask_code("QZ7XKM"), "••••KM")
        self.assertIsNone(wayfare.mask_code(None))


class Batch(unittest.TestCase):
    def test_versions_and_stale_trip_delete(self):
        r = build(SAMPLE)
        existing = {"trips/lisbon-2026-11": 4, "trips/old-trip-2026-01": 2, "meta/status": 9}
        w = wayfare.batch_writes(r, PROFILE, existing, include_profile=False)
        by = {(x["collection"], x["doc_id"]): x for x in w}
        self.assertEqual(by[("trips", "lisbon-2026-11")]["if_version"], 4)
        self.assertNotIn("if_version", by[("trips", "berlin-2026-12")])
        self.assertEqual(by[("trips", "old-trip-2026-01")]["op"], "delete")
        self.assertEqual(by[("meta", "status")]["if_version"], 9)
        self.assertNotIn(("private", "profile"), by)

    def test_sample_build_never_writes_bookings(self):
        w = wayfare.batch_writes(build(SAMPLE), PROFILE, {}, include_profile=False, write_bookings=False)
        self.assertNotIn(("private", "bookings"), {(x["collection"], x["doc_id"]) for x in w})


class Merge(unittest.TestCase):
    def test_schedule_change_email_updates_original(self):
        old = copy.deepcopy(SAMPLE[5])          # KL 1734, Nov 12
        new = {k: old[k] for k in ("type", "carrier", "flightNumber", "from", "to", "fromCity", "toCity", "confirmation")}
        new.update({"id": "flight-KL1734-2026-11-13", "depart": "2026-11-13T07:00:00+00:00",
                    "arrive": "2026-11-13T10:45:00+01:00"})
        merged, notes = wayfare.merge([old], [new])
        self.assertEqual(len(merged), 1)
        m = merged[0]
        self.assertEqual(m["status"], "changed")
        self.assertEqual(m["previous"]["depart"], old["depart"])
        self.assertEqual(m["price"], old["price"])        # kept from the original email
        self.assertTrue(any("schedule change" in n for n in notes))

    def test_new_booking_added_and_cancel(self):
        cancel = {"id": SAMPLE[1]["id"], "type": "hotel", "status": "cancelled", "name": SAMPLE[1]["name"],
                  "city": "Lisbon", "checkIn": "2026-11-06", "checkOut": "2026-11-08", "confirmation": SAMPLE[1]["confirmation"]}
        merged, notes = wayfare.merge(SAMPLE[:2], [cancel, SAMPLE[2]])
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[1]["status"], "cancelled")
        self.assertEqual(wayfare.validate(merged), [])

    def test_saved_db_document_shape_loads(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"data": {"bookings": SAMPLE[:1]}, "version": 3}, f)
        try:
            self.assertEqual(len(wayfare.load_bookings(f.name)), 1)
        finally:
            os.unlink(f.name)


class Fares(unittest.TestCase):
    def offer(self, carrier="KL", number="1734", dep="2026-11-12T12:10:00", amount="230.00", segs=1):
        seg = {"marketing_carrier": {"iata_code": carrier}, "marketing_carrier_flight_number": number, "departing_at": dep}
        return {"id": "off_1", "total_amount": amount, "total_currency": "EUR", "slices": [{"segments": [seg] * segs}]}

    def test_match_same_flight_cheapest(self):
        b = SAMPLE[5]
        resp = {"data": {"offers": [self.offer(amount="260.00"), self.offer(amount="230.00"),
                                    self.offer(number="1736", amount="90.00"), self.offer(segs=2, amount="80.00")]}}
        self.assertEqual(fare_check.best_matching_offer(b, resp)["amount"], 230.0)

    def test_no_match_on_other_time(self):
        resp = {"data": {"offers": [self.offer(dep="2026-11-12T18:00:00")]}}
        self.assertIsNone(fare_check.best_matching_offer(SAMPLE[5], resp))

    def test_candidates_skip_connections(self):
        check, skipped = fare_check.candidates(SAMPLE, NOW)
        ids = [b["id"] for b in check]
        self.assertIn("flight-KL1734-2026-11-12", ids)
        self.assertTrue(any(s["bookingId"] == "flight-LH179-2026-12-06" for s in skipped))

    def test_body(self):
        body = fare_check.offer_request_body(SAMPLE[5])["data"]
        self.assertEqual(body["slices"][0], {"origin": "OPO", "destination": "AMS", "departure_date": "2026-11-12"})
        self.assertEqual(len(body["passengers"]), 2)


if __name__ == "__main__":
    unittest.main()
