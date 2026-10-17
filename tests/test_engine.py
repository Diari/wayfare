"""Run: python3 -m unittest discover -s tests -v"""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CP = ROOT / "plugins" / "wayfare-claude"
sys.path.insert(0, str(CP / "scripts"))
import wayfare  # noqa: E402
import fare_check  # noqa: E402
import flight_status  # noqa: E402
import weather as weather_mod  # noqa: E402
import stay_check  # noqa: E402

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
SAMPLE = json.loads((CP / "samples" / "bookings.sample.json").read_text())
PROFILE = json.loads((CP / "samples" / "profile.sample.json").read_text())


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

    def test_anchor_and_primary(self):
        lis = trips(build(SAMPLE))[0]
        by = {a["kind"]: a for a in lis["alerts"]}
        self.assertEqual(by["tight_dining"]["anchor"], "dining-taberna-azul-2026-11-06")
        self.assertEqual(by["tight_dining"]["primary"]["label"], "Change table time")
        self.assertIn("OpenTable", by["tight_dining"]["primary"]["url"])
        self.assertTrue(by["tight_dining"]["primary"]["manage"])
        self.assertEqual(by["schedule_change"]["anchor"], "flight-TP669-2026-11-06")
        self.assertIsNone(by["lodging_gap"]["anchor"])
        self.assertEqual(by["lodging_gap"]["primary"]["label"], "Search stays")
        ber = trips(build(SAMPLE))[1]
        self.assertEqual(ber["alerts"][0]["anchor"], "flight-LH992-2026-12-06")

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
            plan = wayfare.write_outputs(r, out, versions, CP / "dashboard" / "trip.html")
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
            wayfare.write_outputs(build(SAMPLE, sample=True), out, {}, CP / "dashboard" / "trip.html")
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


class LiveStatus(unittest.TestCase):
    DAY = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)

    def rec(self, **kw):
        r = {"bookingId": "flight-TP669-2026-11-06", "flightDate": "2026-11-06", "state": "scheduled",
             "depScheduled": "2026-11-06T16:55", "arrScheduled": "2026-11-06T18:50",
             "depGate": "D7", "depTerminal": "2", "checkedAt": "2026-11-06T12:30:00+00:00", "source": "test"}
        r.update(kw)
        return r

    def lisbon(self, recs, now=None):
        r = wayfare.build(SAMPLE, PROFILE, [], now or self.DAY, status_list=recs)
        return trips(r)[0]

    def test_delay_moves_times_and_finds_knock_on(self):
        t = self.lisbon([self.rec(depEstimated="2026-11-06T17:55", arrEstimated="2026-11-06T19:50", depDelay=60)])
        k = kinds(t)
        self.assertIn("flight_delayed", k)
        self.assertIn("dining_conflict", k)          # 19:50 arrival, table at 19:30
        f = next(i for i in t["items"] if i["id"] == "flight-TP669-2026-11-06")
        self.assertEqual(f["time"], "16:55")         # booked time stays
        self.assertEqual(f["live"]["label"], "60 min late")
        self.assertEqual(f["live"]["depGate"], "D7")
        a = next(a for a in t["alerts"] if a["kind"] == "flight_delayed")
        self.assertIn("flightradar24.com", a["primary"]["url"])

    def test_delay_fingerprint_is_stable(self):
        a1 = next(a for a in self.lisbon([self.rec(depEstimated="2026-11-06T17:55")])["alerts"] if a["kind"] == "flight_delayed")
        a2 = next(a for a in self.lisbon([self.rec(depEstimated="2026-11-06T18:10")])["alerts"] if a["kind"] == "flight_delayed")
        self.assertEqual((a1["id"], a1["fingerprint"]), (a2["id"], a2["fingerprint"]))

    def test_on_time_has_no_alert(self):
        t = self.lisbon([self.rec(depEstimated="2026-11-06T16:57")])
        self.assertNotIn("flight_delayed", kinds(t))
        f = next(i for i in t["items"] if i["id"] == "flight-TP669-2026-11-06")
        self.assertEqual(f["live"]["label"], "On time")

    def test_cancelled(self):
        t = self.lisbon([self.rec(state="cancelled")])
        self.assertIn("flight_cancelled", kinds(t))
        a = next(a for a in t["alerts"] if a["kind"] == "flight_cancelled")
        self.assertTrue(a["primary"]["manage"])

    def test_stale_status_is_ignored(self):
        t = self.lisbon([self.rec(depEstimated="2026-11-06T18:55", checkedAt="2026-11-05T08:00:00+00:00")])
        self.assertNotIn("flight_delayed", kinds(t))
        f = next(i for i in t["items"] if i["id"] == "flight-TP669-2026-11-06")
        self.assertNotIn("live", f)

    def test_chat_goes_to_private(self):
        r = wayfare.build(SAMPLE, PROFILE, [], NOW, chats={"lisbon-2026-11": {"triggerId": "trig_x", "url": "https://claude.ai/code/session_x"}})
        self.assertEqual(r["trips"][0]["private"]["chat"]["triggerId"], "trig_x")
        self.assertIsNone(r["trips"][1]["private"]["chat"])
        self.assertNotIn("chat", json.dumps(r["trips"][0]["public"]))


class Providers(unittest.TestCase):
    def test_searchapi_match(self):
        def opt(num, time, price, segs=1):
            seg = {"flight_number": num, "departure_airport": {"id": "OPO", "time": time}}
            return {"flights": [seg] * segs, "price": price}
        resp = {"best_flights": [opt("KL 1734", "2026-11-12 12:10", 260), opt("KL 1736", "2026-11-12 18:00", 90)],
                "other_flights": [opt("KL 1734", "12:10", 218), opt("KL 1734", "12:10", 50, segs=2)]}
        m = fare_check.searchapi_match(SAMPLE[5], resp)
        self.assertEqual(m, {"amount": 218.0, "currency": "EUR"})
        self.assertEqual(fare_check.searchapi_params(SAMPLE[5])["adults"], 2)

    def test_aviationstack_pick_and_normalise(self):
        b = SAMPLE[0]
        data = [{"flight_date": "2026-11-05", "departure": {"iata": "AMS"}},
                {"flight_date": "2026-11-06", "flight_status": "active",
                 "departure": {"iata": "AMS", "scheduled": "2026-11-06T16:55:00+00:00", "estimated": "2026-11-06T17:20:00+00:00",
                               "delay": 25, "gate": "D7", "terminal": "2"},
                 "arrival": {"iata": "LIS", "scheduled": "2026-11-06T18:50:00+00:00", "baggage": "5"}}]
        rec = flight_status.normalise(b, flight_status.pick(b, data), NOW)
        self.assertEqual(rec["state"], "active")
        self.assertEqual(rec["depEstimated"], "2026-11-06T17:20")
        self.assertEqual(rec["baggage"], "5")

    def test_status_candidates_window(self):
        day = datetime(2026, 11, 6, 6, 0, tzinfo=timezone.utc)
        check, _ = flight_status.candidates(SAMPLE, {}, day, 30, 90)
        self.assertEqual([b["id"] for b in check], ["flight-TP669-2026-11-06"])


class DaysWeatherRoutes(unittest.TestCase):
    def setUp(self):
        self.lis, self.ber = trips(build(SAMPLE))

    def test_day_cities(self):
        self.assertEqual([d["city"] for d in self.lis["days"]], ["Lisbon"] * 2 + ["Porto"] * 5)
        self.assertEqual(self.lis["days"][0]["date"], "2026-11-06")
        self.assertEqual(self.lis["days"][-1]["date"], "2026-11-12")

    def test_day_routes_split_at_flights(self):
        r = self.lis["dayRoutes"]
        self.assertIn("origin=LIS+airport", r["2026-11-06"])
        self.assertNotIn("AMS", r["2026-11-06"])
        self.assertNotIn("2026-11-12", r)          # only the airport that day

    def test_weather_goes_to_days_and_home(self):
        wx = {"days": [{"city": "Lisbon", "date": "2026-11-06", "hi": 19, "lo": 13, "code": 3, "rain": 10, "kind": "forecast"},
                       {"city": "Porto", "date": "2026-11-09", "hi": 16, "lo": 10, "code": 61, "rain": 80, "kind": "forecast"},
                       {"city": "Porto", "date": "2026-11-06", "hi": 1, "lo": 0, "code": 0, "rain": 0, "kind": "forecast"}],
              "checkedAt": "2026-11-01T06:00:00+00:00"}
        r = build(SAMPLE, weather=wx)
        t = r["trips"][0]
        self.assertEqual([w["date"] for w in t["public"]["weather"]["days"]], ["2026-11-06", "2026-11-09"])
        self.assertEqual([w["city"] for w in t["index"]["weather"]], ["Lisbon", "Porto"])
        self.assertIsNone(r["trips"][1]["public"]["weather"])

    def test_weather_plan(self):
        plan = build(SAMPLE)["weatherPlan"]
        self.assertEqual({p["city"] for p in plan}, {"Lisbon", "Porto", "Berlin"})

    def test_weather_split_and_rows(self):
        from datetime import date
        near, far = weather_mod.split_dates(["2026-10-10", "2026-10-20", "2026-11-20"], date(2026, 10, 15))
        self.assertEqual((near, far), (["2026-10-20"], ["2026-11-20"]))
        rows = weather_mod.daily_rows({"daily": {"time": ["2026-10-20"], "temperature_2m_max": [18.6], "temperature_2m_min": [11.2],
                                                 "weather_code": [61], "precipitation_probability_max": [70]}}, "forecast")
        self.assertEqual(rows["2026-10-20"], {"hi": 19, "lo": 11, "code": 61, "rain": 70, "kind": "forecast"})
        self.assertEqual(weather_mod.shift_year("2028-02-29"), "2027-02-28")

    def test_sample_guides_are_well_formed(self):
        import re
        for slug in ("lisbon-2026-11", "berlin-2026-12"):
            g = json.loads((CP / "samples" / f"guide.{slug}.sample.json").read_text())
            ids = [x["id"] for x in g["pack"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(re.fullmatch(r"[a-z0-9-]{1,40}", i) for i in ids))
            self.assertTrue(all(k["icon"] in {"money", "plug", "tip", "phone", "water", "time", "lang", "id", "safety", "food", "card"} for k in g["know"]))
            for c in g["around"]:
                for it in c["items"]:
                    self.assertTrue(all(l["url"].startswith("https://") for l in it.get("links", [])))


class StayPrices(unittest.TestCase):
    STAY = "hotel-casa-do-largo-2026-11-06"

    def rec(self, **kw):
        r = {"bookingId": self.STAY, "kind": "stay", "paidTotal": 318.0, "liveTotal": 262.0, "currency": "EUR",
             "offerSource": "Booking.com", "offerLink": "https://www.google.com/travel/clk?x=1", "checkedAt": "2026-10-15T20:00:00Z"}
        r.update(kw)
        return r

    def alerts(self, fares, bookings=SAMPLE, now=NOW):
        return [a for a in trips(wayfare.build(bookings, PROFILE, fares, now))[0]["alerts"] if a["kind"] == "stay_price_drop"]

    def test_drop_alert_with_offer_link(self):
        a = self.alerts([self.rec()])
        self.assertEqual(len(a), 1)
        self.assertIn("book the new rate first, then cancel", a[0]["detail"])
        self.assertEqual(a[0]["anchor"], self.STAY)
        self.assertEqual(a[0]["primary"]["url"], "https://www.google.com/travel/clk?x=1")
        self.assertFalse(a[0]["primary"]["manage"])

    def test_small_drop_or_not_refundable_or_deadline_passed(self):
        self.assertEqual(self.alerts([self.rec(liveTotal=300.0)]), [])
        nonref = copy.deepcopy(SAMPLE)
        next(b for b in nonref if b["id"] == self.STAY)["refundable"] = False
        self.assertEqual(self.alerts([self.rec()], nonref), [])
        late = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(self.alerts([self.rec()], now=late), [])

    def test_fingerprint_ignores_new_price(self):
        a1, a2 = self.alerts([self.rec()])[0], self.alerts([self.rec(liveTotal=250.0)])[0]
        self.assertEqual((a1["id"], a1["fingerprint"]), (a2["id"], a2["fingerprint"]))
        self.assertTrue(a2["detail"].startswith("EUR 68 less."))

    def test_name_match_and_candidates(self):
        self.assertTrue(stay_check.same_hotel("Casa do Largo (sample)", "Casa do Largo Lisboa"))
        self.assertFalse(stay_check.same_hotel("Casa do Largo", "Hotel Avenida Palace"))
        check, skipped = stay_check.candidates(SAMPLE, NOW)
        ids = [b["id"] for b in check]
        self.assertIn(self.STAY, ids)
        later = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
        self.assertNotIn(self.STAY, [b["id"] for b in stay_check.candidates(SAMPLE, later)[0]])

    def test_best_offer_needs_free_cancellation(self):
        resp = {"property": {"featured_offers": [
            {"source": "A", "has_free_cancellation": False, "total_price": {"extracted_price": 200}},
            {"source": "B", "has_free_cancellation": True, "total_price": {"extracted_price": 270}, "link": "https://b.example"}],
            "all_offers": [{"source": "C", "has_free_cancellation": True, "total_price": {"extracted_price": 255},
                            "tracking_link": "http://insecure.example"}]}}
        best = stay_check.best_free_cancel_offer(resp)
        self.assertEqual((best["source"], best["total"], best["link"]), ("C", 255.0, None))


class NoMachineCredentials(unittest.TestCase):
    """Claude directory policy: the Claude plugin must not read keys from the
    user's machine. Keys are API credentials added by the cloud proxy."""

    def test_claude_scripts_do_not_read_environment(self):
        import re
        bad = re.compile(r"os\.environ|os\.getenv|getenv\(|load_dotenv|open\([^)]*\.env")
        hits = []
        for f in (CP / "scripts").rglob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if bad.search(line):
                    hits.append(f"{f.name}:{n}: {line.strip()}")
        self.assertEqual(hits, [])

    def test_claude_keys_module_returns_nothing(self):
        import keys
        for s in ("searchapi", "aviationstack", "duffel"):
            self.assertEqual(keys.get(s), "")


if __name__ == "__main__":
    unittest.main()
