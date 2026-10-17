"""Codex / ChatGPT Sites version. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import wayfare  # noqa: E402

NOW = datetime(2026, 10, 15, 20, 0, tzinfo=timezone.utc)
SAMPLE = json.loads((ROOT / "samples" / "bookings.sample.json").read_text())
PROFILE = json.loads((ROOT / "samples" / "profile.sample.json").read_text())


class SiteBundle(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.result = wayfare.build(SAMPLE, PROFILE, [], NOW, sample=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_projects_written(self):
        plan = wayfare.site_bundle(self.result, self.dir, None, {})
        self.assertEqual([s["slug"] for s in plan["sites"]], ["lisbon-2026-11", "berlin-2026-12"])
        for slug in ("lisbon-2026-11", "berlin-2026-12", "home"):
            d = self.dir / slug
            for f in ("worker/index.js", "worker/page.js", "worker/data.js", "build.mjs", "dev.mjs", "package.json",
                      "migrations/0001_wayfare.sql", ".openai/hosting.json", ".gitignore"):
                self.assertTrue((d / f).exists(), f"{slug}/{f}")
        data = wayfare.read_site_data(self.dir / "lisbon-2026-11")
        self.assertEqual(data["kind"], "trip")
        self.assertIn("QZ7XKM", json.dumps(data["private"]))          # owner-only part, served by the worker
        self.assertNotIn("QZ7XKM", json.dumps(data["trip"]))
        page = (self.dir / "lisbon-2026-11" / "worker" / "page.js").read_text()
        self.assertIn("WAYFARE_SITE", page)
        self.assertIn("<!doctype html>", page)
        self.assertNotIn("QZ7XKM", page)

    def test_hosting_link_kept_and_changes_detected(self):
        wayfare.site_bundle(self.result, self.dir, None, {})
        hosting = self.dir / "lisbon-2026-11" / ".openai" / "hosting.json"
        hosting.write_text('{"project_id": "proj_1", "d1": "DB", "r2": null}')
        plan = wayfare.site_bundle(self.result, self.dir, None, {"lisbon-2026-11": "https://a.example"})
        self.assertIn("proj_1", hosting.read_text())
        lis = plan["sites"][0]
        self.assertEqual((lis["new"], lis["changed"]), (False, False))
        self.assertTrue(plan["sites"][1]["new"])                     # Berlin still has no URL
        self.assertTrue(plan["home"]["changed"])                      # Home now links to Lisbon
        home = wayfare.read_site_data(self.dir / "home")
        self.assertEqual(home["index"]["trips"][0]["url"], "https://a.example")

    def test_guide_included(self):
        g = self.dir / "guides"; g.mkdir()
        shutil.copy(ROOT / "samples" / "guide.lisbon-2026-11.sample.json", g / "lisbon-2026-11.json")
        wayfare.site_bundle(self.result, self.dir / "sites", g, {})
        self.assertEqual(wayfare.read_site_data(self.dir / "sites" / "lisbon-2026-11")["guide"]["cities"], ["Lisbon", "Porto"])
        self.assertIsNone(wayfare.read_site_data(self.dir / "sites" / "berlin-2026-12")["guide"])

    def test_slug_kept_from_last_home(self):
        sites = self.dir / "s"
        args = ["site-bundle", "--bookings", str(ROOT / "samples" / "bookings.sample.json"), "--profile",
                str(ROOT / "samples" / "profile.sample.json"), "--sample", "--now", "2026-10-15T20:00:00+00:00",
                "--sites-dir", str(sites)]
        subprocess.run([sys.executable, str(ROOT / "scripts" / "wayfare.py")] + args, check=True, capture_output=True)
        # Add a stay to the Lisbon trip: it must stay on the same Site.
        more = SAMPLE + [{"id": "hotel-extra-2026-11-10", "type": "hotel", "name": "Extra", "city": "Porto",
                          "checkIn": "2026-11-10", "checkOut": "2026-11-12"}]
        f = self.dir / "b.json"; f.write_text(json.dumps(more))
        args[2] = str(f)
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "wayfare.py")] + args, check=True, capture_output=True, text=True)
        self.assertEqual([s["slug"] for s in json.loads(out.stdout)["sites"]], ["lisbon-2026-11", "berlin-2026-12"])


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Worker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        wayfare.site_bundle(wayfare.build(SAMPLE, PROFILE, [], NOW, sample=True), cls.dir, None, {})
        cls.port = free_port()
        env = dict(os.environ, OWNER_EMAIL="owner@example.com", EDITOR_EMAILS="ed@example.com", SITE_DIR=str(cls.dir / "lisbon-2026-11"))
        cls.proc = subprocess.Popen(["node", "--no-warnings", str(cls.dir / "lisbon-2026-11" / "dev.mjs"), str(cls.port)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/state", timeout=1); break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(5)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, method, path, body=None, email=None, origin=None):
        h = {"content-type": "application/json"}
        if email: h["oai-authenticated-user-email"] = email
        if origin: h["origin"] = origin
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def state(self, email=None):
        return json.loads(self.call("GET", "/api/state", email=email)[1])

    def test_private_only_for_owner(self):
        self.assertIsNone(self.state()["private"])
        self.assertIsNone(self.state("friend@example.com")["private"])
        self.assertIn("QZ7XKM", json.dumps(self.state("OWNER@example.com")["private"]))

    def test_permissions(self):
        a = {"status": "done", "fingerprint": "abc"}
        self.assertEqual(self.call("PUT", "/api/actions/x1", a, "friend@example.com")[0], 403)
        self.assertEqual(self.call("PUT", "/api/actions/x1", a, "ed@example.com")[0], 200)
        self.assertEqual(self.state()["actions"]["x1"]["status"], "done")
        self.assertEqual(self.call("POST", "/api/todos", {"text": "Insurance"})[0], 401)
        st, body = self.call("POST", "/api/todos", {"text": "Insurance"}, "friend@example.com")
        self.assertEqual(st, 200)
        tid = json.loads(body)["id"]
        self.assertEqual(self.call("DELETE", f"/api/todos/{tid}", None, "friend@example.com")[0], 403)
        self.assertEqual(self.call("POST", "/api/todos", {"text": "x"}, "owner@example.com", origin="https://evil.example")[0], 403)

    def test_packing_is_per_person(self):
        self.call("PUT", "/api/packing", {"done": ["umbrella", "BAD ID"]}, "friend@example.com")
        self.assertEqual(self.state("friend@example.com")["packing"], ["umbrella"])
        self.assertEqual(self.state("owner@example.com")["packing"], [])

    def test_calendar_file(self):
        st, body = self.call("GET", "/trip.ics")
        self.assertEqual(st, 200)
        self.assertIn("BEGIN:VEVENT", body)
        self.assertIn("DTSTART;VALUE=DATE:20261106", body)
        self.assertNotIn("QZ7XKM", body)


class CodexPackage(unittest.TestCase):
    def test_validator(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_codex.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_shared_files_in_sync(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "sync_codex.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + " (run python3 tools/sync_codex.py)")


if __name__ == "__main__":
    unittest.main()
