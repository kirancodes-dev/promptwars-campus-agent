import os
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

try:
    from api.agent import clear_pending_approvals, get_orchestrator
    from main import app
    from models.agent import AgentPlan, AgentTask
    from tools.notes import _notes
    from tools.schedule import _events
    from tools.tasks import _tasks, create_task
except ImportError:
    from backend.api.agent import clear_pending_approvals, get_orchestrator
    from backend.main import app
    from backend.models.agent import AgentPlan, AgentTask
    from backend.tools.notes import _notes
    from backend.tools.schedule import _events
    from backend.tools.tasks import _tasks, create_task


class TestAgentAPI(unittest.TestCase):
    def setUp(self):
        # These tests mix direct tool calls (demo user) with API calls, so they run in
        # shared demo identity mode. Session isolation is covered in test_security.py.
        self._env = patch.dict(os.environ, {"IDENTITY_MODE": "demo"})
        self._env.start()
        from main import rate_limiter
        rate_limiter.reset()
        self.client = TestClient(app)
        clear_pending_approvals()
        _tasks.clear()
        _events.clear()
        _notes.clear()
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()
        clear_pending_approvals()
        self._env.stop()

    def test_get_status_returns_healthy(self):
        """1. GET /api/agent/status returns healthy."""
        response = self.client.get("/api/agent/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["service"], "CampusPilot AI")
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["agent"], "ready")
        self.assertIn(data["planner"], ["deterministic", "gemini"])

    def test_post_plan_accepts_valid_goal(self):
        """2. POST /api/agent/plan accepts a valid goal."""
        response = self.client.post("/api/agent/plan", json={"goal": "Show my tasks"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["goal"], "Show my tasks")
        self.assertIn("tasks", data)
        self.assertTrue(len(data["tasks"]) > 0)

    def test_post_plan_rejects_empty_goal(self):
        """3. POST /api/agent/plan rejects an empty goal."""
        r1 = self.client.post("/api/agent/plan", json={"goal": ""})
        self.assertEqual(r1.status_code, 400)
        self.assertIn("empty", r1.json()["detail"].lower())

        r2 = self.client.post("/api/agent/plan", json={"goal": "   "})
        self.assertEqual(r2.status_code, 400)

    def test_post_plan_does_not_execute_tools(self):
        """4. POST /api/agent/plan does not execute tools."""
        self.assertEqual(len(_tasks), 0)
        response = self.client.post(
            "/api/agent/plan",
            json={"goal": "Create a task to study DBMS"},
        )
        self.assertEqual(response.status_code, 200)
        # Verification that no task was actually inserted into storage
        self.assertEqual(len(_tasks), 0)

    def test_post_run_supports_read_only_operations(self):
        """5. POST /api/agent/run supports read-only operations."""
        response = self.client.post(
            "/api/agent/run",
            json={"goal": "Show my tasks", "approved": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "completed")
        self.assertFalse(data["requires_approval"])
        self.assertEqual(len(data["results"]), 1)
        self.assertTrue(data["results"][0]["success"])
        self.assertEqual(data["results"][0]["tool_name"], "get_tasks")

    def test_post_run_blocks_approval_required_operations(self):
        """6. POST /api/agent/run blocks approval-required operations when approved=false."""
        from agent.orchestrator import AgentOrchestrator

        def protected_planner(goal):
            task = AgentTask(
                id="t_prot",
                title="Delete task",
                tool="delete_task",
                parameters={"task_id": "dummy_id"},
                requires_approval=True,
            )
            return AgentPlan(
                goal=goal.goal,
                summary="Protected delete plan",
                tasks=[task],
                requires_approval=True,
            )

        app.dependency_overrides[get_orchestrator] = lambda: AgentOrchestrator(
            planner_func=protected_planner
        )

        response = self.client.post(
            "/api/agent/run",
            json={"goal": "Delete task dummy_id", "approved": False},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "waiting_approval")
        self.assertTrue(data["requires_approval"])
        self.assertIsNotNone(data.get("approval_id"))
        self.assertTrue(len(data.get("approval_requests", [])) > 0)
        self.assertFalse(data["results"][0]["success"])

    def test_approval_workflow_works_correctly(self):
        """7. Approval workflow works correctly from run -> waiting_approval -> approve -> execute."""
        from agent.orchestrator import AgentOrchestrator

        # 1. Create a task in memory
        created = create_task(title="Task to delete through API")
        task_id = created.id

        def delete_planner(goal):
            task = AgentTask(
                id="t_del",
                title="Delete created task",
                tool="delete_task",
                parameters={"task_id": task_id},
                requires_approval=True,
            )
            return AgentPlan(
                goal=goal.goal,
                summary="Plan to delete task",
                tasks=[task],
                requires_approval=True,
            )

        app.dependency_overrides[get_orchestrator] = lambda: AgentOrchestrator(
            planner_func=delete_planner
        )

        # 2. Call run without approval -> waiting_approval
        run_res = self.client.post(
            "/api/agent/run",
            json={"goal": "Delete created task", "approved": False},
        )
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.json()
        self.assertEqual(run_data["status"], "waiting_approval")
        approval_id = run_data["approval_id"]
        self.assertIsNotNone(approval_id)
        self.assertIn(task_id, _tasks)  # Still not deleted!

        # 3. Call approve endpoint
        appr_res = self.client.post(
            "/api/agent/approve",
            json={"approval_id": approval_id, "approved": True},
        )
        self.assertEqual(appr_res.status_code, 200)
        appr_data = appr_res.json()
        self.assertEqual(appr_data["status"], "approved")
        self.assertTrue(appr_data["success"])
        self.assertEqual(appr_data["tool_name"], "delete_task")

        # 4. Verify task is actually deleted from storage
        self.assertNotIn(task_id, _tasks)

    def test_rejected_approval_never_executes_a_tool(self):
        """8. Rejected approval never executes a tool."""
        from agent.orchestrator import AgentOrchestrator

        created = create_task(title="Protected task from rejection")
        task_id = created.id

        def delete_planner(goal):
            task = AgentTask(
                id="t_del",
                title="Delete created task",
                tool="delete_task",
                parameters={"task_id": task_id},
                requires_approval=True,
            )
            return AgentPlan(
                goal=goal.goal,
                summary="Plan to delete task",
                tasks=[task],
                requires_approval=True,
            )

        app.dependency_overrides[get_orchestrator] = lambda: AgentOrchestrator(
            planner_func=delete_planner
        )

        run_res = self.client.post(
            "/api/agent/run",
            json={"goal": "Delete protected task", "approved": False},
        )
        run_data = run_res.json()
        approval_id = run_data["approval_id"]

        # Call reject
        rej_res = self.client.post(
            "/api/agent/reject",
            json={"approval_id": approval_id},
        )
        self.assertEqual(rej_res.status_code, 200)
        rej_data = rej_res.json()
        self.assertEqual(rej_data["status"], "rejected")
        self.assertIsNone(rej_data["tool_result"])

        # Verify task is STILL in storage
        self.assertIn(task_id, _tasks)

    def test_unknown_approval_id_is_rejected(self):
        """9. Unknown approval ID is rejected with 404."""
        r1 = self.client.post(
            "/api/agent/approve",
            json={"approval_id": "appr_nonexistent_123", "approved": True},
        )
        self.assertEqual(r1.status_code, 404)

        r2 = self.client.post(
            "/api/agent/reject",
            json={"approval_id": "appr_nonexistent_123"},
        )
        self.assertEqual(r2.status_code, 404)

    def test_invalid_request_body_is_rejected(self):
        """10. Invalid request body is rejected with 422."""
        r1 = self.client.post("/api/agent/plan", json={"wrong_field": 123})
        self.assertEqual(r1.status_code, 422)

        r2 = self.client.post("/api/agent/run", json={"wrong_field": 123})
        self.assertEqual(r2.status_code, 422)

    def test_api_never_accepts_arbitrary_tool_execution(self):
        """11. API never accepts arbitrary tool execution."""
        # Client tries sending direct tool execution payload to approve
        malicious_payload = {
            "tool_name": "delete_task",
            "parameters": {"task_id": "random"},
            "approved": True,
        }
        res = self.client.post("/api/agent/approve", json=malicious_payload)
        self.assertIn(res.status_code, [400, 404, 422])

    def test_api_does_not_expose_secrets(self):
        """12. API does not expose secrets or sensitive configuration."""
        endpoints = [
            ("/api/agent/status", "GET", None),
            ("/api/agent/plan", "POST", {"goal": "Show tasks"}),
            ("/api/agent/run", "POST", {"goal": "Show tasks", "approved": False}),
        ]
        for path, method, payload in endpoints:
            if method == "GET":
                res = self.client.get(path)
            else:
                res = self.client.post(path, json=payload)
            body = res.text
            self.assertNotIn("AIza", body)
            self.assertNotIn("api_key", body.lower())
            self.assertNotIn("secret", body.lower())

    def test_api_uses_the_agent_orchestrator(self):
        """13. API uses the AgentOrchestrator."""
        from agent.orchestrator import AgentOrchestrator

        spy_orchestrator = MagicMock(spec=AgentOrchestrator)
        spy_orchestrator.plan.return_value = AgentPlan(
            goal="Test goal",
            summary="Test summary",
            tasks=[],
            requires_approval=False,
        )

        app.dependency_overrides[get_orchestrator] = lambda: spy_orchestrator

        res = self.client.post("/api/agent/plan", json={"goal": "Test goal"})
        self.assertEqual(res.status_code, 200)
        spy_orchestrator.plan.assert_called_once()

    def test_gemini_unavailable_fallback_works(self):
        """14. Gemini-unavailable fallback works without crashing."""
        with patch("api.agent.get_gemini_service_safe", return_value=None):
            res = self.client.get("/api/agent/status")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["planner"], "deterministic")

            plan_res = self.client.post("/api/agent/plan", json={"goal": "Show my tasks"})
            self.assertEqual(plan_res.status_code, 200)
            self.assertEqual(plan_res.json()["goal"], "Show my tasks")

    def test_no_eval_used(self):
        """15. No eval() is used in backend/api/agent.py."""
        path = pathlib.Path(__file__).parent / "agent.py"
        content = path.read_text()
        self.assertNotIn("eval(", content)

    def test_no_exec_used(self):
        """16. No exec() is used in backend/api/agent.py."""
        path = pathlib.Path(__file__).parent / "agent.py"
        content = path.read_text()
        self.assertNotIn("exec(", content)

    def test_health_endpoint_returns_healthy(self):
        """17. GET /health returns 200 with status healthy."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "healthy"})

    def test_unknown_api_endpoints_return_json_not_html(self):
        """18. Unknown API endpoints return 404 JSON, never index.html."""
        # GET on nonexistent API path
        res_get = self.client.get("/api/unknown_endpoint")
        self.assertEqual(res_get.status_code, 404)
        self.assertTrue(res_get.headers.get("content-type", "").startswith("application/json"))
        self.assertNotIn("<!doctype html>", res_get.text.lower())
        self.assertEqual(res_get.json(), {"detail": "API endpoint not found"})

        # POST on nonexistent API path
        res_post = self.client.post("/api/unknown_endpoint", json={})
        self.assertEqual(res_post.status_code, 404)
        self.assertTrue(res_post.headers.get("content-type", "").startswith("application/json"))
        self.assertNotIn("<!doctype html>", res_post.text.lower())
        self.assertEqual(res_post.json(), {"detail": "API endpoint not found"})

    def test_frontend_routes_served(self):
        """19. Root and client routes serve SPA index.html when present."""
        from main import FRONTEND_DIR

        if not (FRONTEND_DIR / "index.html").is_file():
            self.skipTest("frontend/dist not built; run `npm run build` in frontend/ first")
        res_root = self.client.get("/")
        self.assertEqual(res_root.status_code, 200)
        self.assertIn("<!doctype html>", res_root.text.lower())

        res_spa = self.client.get("/study-planner")
        self.assertEqual(res_spa.status_code, 200)
        self.assertIn("<!doctype html>", res_spa.text.lower())


if __name__ == "__main__":
    unittest.main()
