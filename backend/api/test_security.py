"""STEP 28 — API security tests: session isolation, approval integrity (binding, replay,
tampering, expiry), client approval-flag bypass, input limits, rate limiting, headers,
honest storage status, and secret hygiene. Runs in the default IDENTITY_MODE=session."""

from datetime import datetime, timedelta
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from api.agent import clear_pending_approvals, get_orchestrator
from main import app, rate_limiter
from services.approvals import approval_store
from services.identity import SESSION_COOKIE_NAME
from services.in_memory import InMemoryPersistence
from services.persistence import get_persistence, get_persistence_status, reset_persistence, set_persistence

FLAGSHIP = (
    "Organize my preparation for tomorrow. I need 2 hours of DBMS, 1 hour of DAA, "
    "and I have a project meeting at 4 PM."
)


class SecurityTestBase(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"IDENTITY_MODE": "session", "RATE_LIMIT_PER_MINUTE": "1000"})
        self._env.start()
        self.store = InMemoryPersistence()
        set_persistence(self.store, mode="memory")
        clear_pending_approvals()
        rate_limiter.reset()
        app.dependency_overrides.clear()
        self.alice = TestClient(app)
        self.bob = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        clear_pending_approvals()
        reset_persistence()
        self._env.stop()

    def stage(self, client, goal=FLAGSHIP):
        res = client.post("/api/agent/run", json={"goal": goal})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["status"], "waiting_approval")
        return data

    def all_events(self):
        return sum(len(v) for v in self.store._events.values())


class TestSessionIsolation(SecurityTestBase):
    def test_session_cookie_is_issued_and_hardened(self):
        res = self.alice.get("/api/agent/status")
        cookie = res.headers.get("set-cookie", "")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_page_load_issues_the_session_before_api_calls(self):
        """Regression: parallel first API calls must not each mint a different session."""
        from main import FRONTEND_DIR

        if not (FRONTEND_DIR / "index.html").is_file():
            self.skipTest("frontend/dist not built")
        page = self.alice.get("/")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", page.headers.get("set-cookie", ""))
        # Every API call after the page load reuses that session: no new cookies issued.
        for path in ("/api/agent/status", "/api/agent/memory", "/api/agent/workflows", "/api/agent/audit"):
            self.assertNotIn("set-cookie", self.alice.get(path).headers)
        data = self.stage(self.alice)
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]}).status_code, 200)

    def test_concurrent_initial_requests_share_one_session(self):
        """Regression: after the page load, parallel first requests (as the SPA sends them) use one session."""
        from concurrent.futures import ThreadPoolExecutor
        from main import FRONTEND_DIR

        if not (FRONTEND_DIR / "index.html").is_file():
            self.skipTest("frontend/dist not built")
        cookie = self.alice.get("/").cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(cookie)

        def call(req):
            client = TestClient(app)
            client.cookies.set(SESSION_COOKIE_NAME, cookie)
            method, path = req
            if method == "POST":
                return client.post(path, json={"goal": "Prepare for tomorrow: 1 hour of OS"})
            return client.get(path)

        reqs = [("GET", "/api/agent/status"), ("GET", "/api/agent/memory"), ("GET", "/api/agent/workflows"),
                ("GET", "/api/agent/audit"), ("POST", "/api/agent/run")]
        with ThreadPoolExecutor(max_workers=len(reqs)) as pool:
            responses = list(pool.map(call, reqs))
        for (method, path), res in zip(reqs, responses):
            self.assertEqual(res.status_code, 200, path)
            self.assertNotIn("set-cookie", res.headers, f"{method} {path} minted a new session")
        approval_id = responses[-1].json()["approval_id"]
        # The approval created inside the concurrent batch belongs to the page-load session.
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": approval_id}).status_code, 200)
        self.assertEqual(self.bob.post("/api/agent/approve", json={"approval_id": approval_id}).status_code, 404)

    def test_forged_cookie_on_page_load_is_replaced(self):
        client = TestClient(app)
        client.cookies.set(SESSION_COOKIE_NAME, "0" * 32 + ".forged")
        res = client.get("/")
        self.assertIn(f"{SESSION_COOKIE_NAME}=", res.headers.get("set-cookie", ""))
        self.assertNotIn("0" * 32 + ".forged", res.headers.get("set-cookie", ""))

    def test_static_files_and_health_stay_cookie_free(self):
        for path in ("/health", "/favicon.svg", "/assets/missing.js"):
            self.assertNotIn("set-cookie", TestClient(app).get(path).headers, path)

    def test_late_parallel_session_cannot_hijack_pending_approval_lookup(self):
        """Simulates the race: a stale parallel response replaces the cookie -> approval is 404, never executed."""
        data = self.stage(self.alice)
        stray = TestClient(app).get("/api/agent/status").cookies.get(SESSION_COOKIE_NAME)
        self.alice.cookies.set(SESSION_COOKIE_NAME, stray)
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]}).status_code, 404)
        self.assertEqual(self.all_events(), 0)

    def test_users_cannot_see_each_others_data(self):
        data = self.stage(self.alice)
        res = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["success"])

        alice_wf = self.alice.get("/api/agent/workflows").json()
        bob_wf = self.bob.get("/api/agent/workflows").json()
        self.assertGreaterEqual(len(alice_wf), 1)
        self.assertEqual(bob_wf, [])
        self.assertEqual(self.bob.get("/api/agent/audit").json(), [])
        self.assertEqual(self.bob.get(f"/api/agent/workflows/{alice_wf[0]['workflow_id']}").status_code, 404)

        bob_tasks = self.bob.post("/api/agent/run", json={"goal": "Show my tasks"}).json()
        self.assertEqual(bob_tasks["results"][0]["result"]["tasks"], [])
        alice_tasks = self.alice.post("/api/agent/run", json={"goal": "Show my tasks"}).json()
        self.assertEqual(len(alice_tasks["results"][0]["result"]["tasks"]), 1)

    def test_other_user_cannot_approve_or_reject(self):
        data = self.stage(self.alice)
        for path in ("/api/agent/approve", "/api/agent/reject"):
            res = self.bob.post(path, json={"approval_id": data["approval_id"]})
            self.assertEqual(res.status_code, 404)
        for req in data["approval_requests"]:
            self.assertEqual(self.bob.post("/api/agent/approve", json={"approval_id": req["approval_id"]}).status_code, 404)
        res = self.bob.post("/api/agent/approve", json={"goal": FLAGSHIP})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.all_events(), 0)

    def test_forged_cookie_gets_fresh_session(self):
        data = self.stage(self.alice)
        forged = TestClient(app)
        forged.cookies.set(SESSION_COOKIE_NAME, "0" * 32 + ".deadbeef")
        res = forged.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(res.status_code, 404)
        self.assertIn(f"{SESSION_COOKIE_NAME}=", res.headers.get("set-cookie", ""))

    def test_preferences_are_isolated(self):
        prop = self.alice.post("/api/agent/memory/propose", json={"updates": {"preferred_break_minutes": 25}}).json()
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": prop["approval_id"]}).status_code, 200)
        self.assertEqual(self.alice.get("/api/agent/memory").json()["preferences"]["preferred_break_minutes"], 25)
        self.assertEqual(self.bob.get("/api/agent/memory").json()["preferences"]["preferred_break_minutes"], 10)


class TestApprovalIntegrity(SecurityTestBase):
    def test_client_approved_flag_on_run_is_ignored(self):
        res = self.alice.post("/api/agent/run", json={"goal": FLAGSHIP, "approved": True})
        self.assertEqual(res.json()["status"], "waiting_approval")
        self.assertEqual(self.all_events(), 0)

    def test_approval_executes_exactly_once(self):
        data = self.stage(self.alice)
        first = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.all_events(), 2)
        replay = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(replay.status_code, 409)
        alias_replay = self.alice.post(
            "/api/agent/approve", json={"approval_id": data["approval_requests"][1]["approval_id"]}
        )
        self.assertEqual(alias_replay.status_code, 409)
        self.assertEqual(self.alice.post("/api/agent/reject", json={"approval_id": data["approval_id"]}).status_code, 409)
        self.assertEqual(self.all_events(), 2)

    def test_rejected_actions_never_execute(self):
        data = self.stage(self.alice)
        rej = self.alice.post("/api/agent/reject", json={"approval_id": data["approval_id"]})
        self.assertEqual(rej.status_code, 200)
        body = rej.json()
        self.assertEqual(body["status"], "rejected")
        self.assertEqual(body["execution_result"]["status"], "rejected")
        self.assertEqual(body["execution_result"]["workflow"]["status"], "rejected")
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]}).status_code, 409)
        self.assertEqual(self.all_events(), 0)

    def test_payload_hash_binding(self):
        data = self.stage(self.alice)
        bad = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"], "payload_hash": "0" * 64})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.all_events(), 0)
        good_hash = data["approval_requests"][0]["payload_hash"]
        ok = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"], "payload_hash": good_hash})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.all_events(), 2)

    def test_parameter_substitution_rejected(self):
        data = self.stage(self.alice)
        params = dict(data["approval_requests"][0]["parameters"])
        params["title"] = "Something else entirely"
        res = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"], "parameters": params})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Tampered", res.json()["detail"])
        self.assertEqual(self.all_events(), 0)

    def test_server_side_plan_mutation_detected(self):
        data = self.stage(self.alice)
        staged = approval_store._by_id[data["approval_id"]]
        target = next(t for t in staged.plan.tasks if t.id == staged.protected_step_ids[0])
        target.parameters["title"] = "Mutated after review"
        res = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.all_events(), 0)

    def test_expired_approval_rejected(self):
        data = self.stage(self.alice)
        approval_store._by_id[data["approval_id"]].expires_at = datetime.now() - timedelta(seconds=1)
        res = self.alice.post("/api/agent/approve", json={"approval_id": data["approval_id"]})
        self.assertEqual(res.status_code, 410)
        self.assertIn("expired", res.json()["detail"])
        self.assertEqual(self.all_events(), 0)

    def test_unknown_and_malformed_approvals(self):
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": "appr_nope"}).status_code, 404)
        self.assertEqual(self.alice.post("/api/agent/approve", json={}).status_code, 400)
        self.assertEqual(
            self.alice.post("/api/agent/approve", json={"tool_name": "delete_task", "parameters": {}}).status_code, 422
        )
        self.assertEqual(self.alice.post("/api/agent/approve", json={"approval_id": "x", "approved": False}).status_code, 400)

    def test_two_workflows_do_not_share_approvals(self):
        a = self.stage(self.alice)
        b = self.stage(self.alice, goal="Prepare for tomorrow: 1 hour of OS")
        self.assertNotEqual(a["approval_id"], b["approval_id"])
        self.alice.post("/api/agent/approve", json={"approval_id": b["approval_id"]})
        titles = sorted(e.title for e in self.store.get_events(user_id=list(self.store._events)[0]))
        self.assertEqual(titles, ["OS Study Block"])

    def test_memory_proposal_executes_and_verifies(self):
        prop = self.alice.post(
            "/api/agent/memory/propose",
            json={"updates": {"preferred_study_start": "17:00", "preferred_study_end": "22:00"}},
        )
        self.assertEqual(prop.status_code, 200)
        body = prop.json()
        self.assertEqual({c["field"] for c in body["changes"]}, {"preferred_study_start", "preferred_study_end"})
        self.assertEqual(self.alice.get("/api/agent/memory").json()["preferences"]["preferred_study_start"], "09:00")
        res = self.alice.post("/api/agent/approve", json={"approval_id": body["approval_id"]}).json()
        self.assertTrue(res["success"])
        self.assertTrue(res["execution_result"]["workflow"]["steps"][0]["verification"]["passed"])
        self.assertEqual(self.alice.get("/api/agent/memory").json()["preferences"]["preferred_study_start"], "17:00")


class TestInputValidation(SecurityTestBase):
    def test_goal_limits(self):
        self.assertEqual(self.alice.post("/api/agent/run", json={"goal": ""}).status_code, 400)
        self.assertEqual(self.alice.post("/api/agent/run", json={"goal": "x" * 1001}).status_code, 422)
        self.assertEqual(self.alice.post("/api/agent/plan", json={"goal": 123}).status_code, 422)

    def test_invalid_json_and_oversized_body(self):
        res = self.alice.post("/api/agent/run", content=b"{not json", headers={"content-type": "application/json"})
        self.assertEqual(res.status_code, 422)
        res = self.alice.post("/api/agent/run", content=b"x" * 40000, headers={"content-type": "application/json"})
        self.assertEqual(res.status_code, 413)

    def test_invalid_preferences_rejected(self):
        cases = [
            {"preferred_study_start": "25:00"},
            {"preferred_session_minutes": -5},
            {"preferred_break_minutes": 9999},
            {"preferred_study_days": ["Funday"]},
            {"planning_notes": ["my password is hunter2"]},
            {"favourite_colour": "blue"},
            {},
        ]
        for updates in cases:
            res = self.alice.post("/api/agent/memory/propose", json={"updates": updates})
            self.assertEqual(res.status_code, 400, updates)
        res = self.alice.post(
            "/api/agent/memory/propose", json={"updates": {"preferred_study_start": "22:00", "preferred_study_end": "08:00"}}
        )
        self.assertEqual(res.status_code, 400)

    def test_direct_form_edit_is_validated_and_verified(self):
        res = self.alice.post("/api/agent/memory/update", json={"updates": {"preferred_break_minutes": 15}, "approved": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["verified"])
        bad = self.alice.post("/api/agent/memory/update", json={"updates": {"preferred_break_minutes": 500}, "approved": True})
        self.assertEqual(bad.status_code, 400)

    def test_reset_requires_confirmation(self):
        self.assertEqual(self.alice.post("/api/agent/memory/reset", json={"confirm": False}).status_code, 400)
        self.assertEqual(self.alice.post("/api/agent/memory/reset", json={}).status_code, 422)
        ok = self.alice.post("/api/agent/memory/reset", json={"confirm": True})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["verified"])

    def test_audit_limit_bounds(self):
        self.assertEqual(self.alice.get("/api/agent/audit?limit=5000").status_code, 422)


class TestPlatformHardening(SecurityTestBase):
    def test_rate_limit(self):
        with patch.dict(os.environ, {"RATE_LIMIT_PER_MINUTE": "3"}):
            codes = [self.alice.post("/api/agent/plan", json={"goal": "Show my tasks"}).status_code for _ in range(4)]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3], 429)
        self.assertEqual(self.bob.post("/api/agent/plan", json={"goal": "Show my tasks"}).status_code, 200)

    def test_cross_site_simple_requests_rejected(self):
        """CSRF-style 'simple' requests (text/plain, form) cannot drive JSON endpoints."""
        body = b'{"goal": "Organize my preparation for tomorrow. I need 2 hours of DBMS"}'
        for ctype in ("text/plain", "application/x-www-form-urlencoded"):
            res = self.alice.post("/api/agent/run", content=body, headers={"content-type": ctype})
            self.assertEqual(res.status_code, 422, ctype)
        self.assertEqual(self.alice.post("/api/agent/approve", content=b"approval_id=x", headers={"content-type": "application/x-www-form-urlencoded"}).status_code, 422)

    def test_security_headers(self):
        res = self.alice.get("/api/agent/status")
        self.assertEqual(res.headers["x-content-type-options"], "nosniff")
        self.assertEqual(res.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", res.headers["content-security-policy"])
        self.assertEqual(res.headers["cache-control"], "no-store")

    def test_internal_errors_hide_details(self):
        class Boom:
            def plan(self, goal):
                raise RuntimeError("secret internal path /etc/thing")

        app.dependency_overrides[get_orchestrator] = lambda: Boom()
        res = self.alice.post("/api/agent/plan", json={"goal": "anything"})
        self.assertEqual(res.status_code, 500)
        self.assertNotIn("/etc/thing", res.text)
        self.assertNotIn("Traceback", res.text)

    def test_status_never_leaks_secret_values(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy-secret-value-123"}):
            body = self.alice.get("/api/agent/status").text
        self.assertNotIn("dummy-secret-value-123", body)

    def test_status_reports_memory_fallback_honestly(self):
        reset_persistence()
        with patch.dict(os.environ, {"FIRESTORE_ENABLED": "true"}), patch(
            "services.firestore.init_firestore", return_value=None
        ):
            get_persistence()
            status = get_persistence_status()
            api_status = self.alice.get("/api/agent/status").json()
        self.assertEqual(status["mode"], "memory_fallback")
        self.assertFalse(status["durable"])
        self.assertEqual(api_status["persistence_mode"], "memory_fallback")
        self.assertFalse(api_status["persistence_durable"])
        self.assertIn("lost on restart", api_status["persistence_message"])

    def test_missing_static_file_is_404_not_spa(self):
        self.assertEqual(self.alice.get("/assets/does-not-exist.js").status_code, 404)
        self.assertEqual(self.alice.get("/missing-file.js").status_code, 404)


if __name__ == "__main__":
    unittest.main()
