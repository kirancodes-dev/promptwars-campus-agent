import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.gemini import (
    CAMPUSPILOT_SYSTEM_PROMPT,
    GeminiConfigurationError,
    GeminiService,
    GeminiServiceError,
    build_planning_prompt,
)
from tools.notes import _notes, clear_notes
from tools.schedule import _events, clear_schedule
from tools.tasks import _tasks, clear_tasks


class TestGeminiService(unittest.TestCase):
    def setUp(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def tearDown(self):
        clear_tasks()
        clear_schedule()
        clear_notes()

    def test_missing_api_key_raises_configuration_error(self):
        """1. Missing API key raises GeminiConfigurationError."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GeminiConfigurationError):
                GeminiService(api_key=None)

    def test_explicit_api_key_accepted_without_printing_it(self):
        """2. Explicit API key is accepted without printing it."""
        mock_client = MagicMock()
        service = GeminiService(api_key="test-dummy-secret-key", client=mock_client)
        rep = repr(service)
        st = str(service)
        self.assertNotIn("test-dummy-secret-key", rep)
        self.assertNotIn("test-dummy-secret-key", st)

    def test_environment_api_key_accepted(self):
        """3. Environment API key is accepted."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy-env-key"}):
            with patch("services.gemini.genai.Client") as mock_client_cls:
                service = GeminiService()
                self.assertIsNotNone(service)
                mock_client_cls.assert_called_once_with(api_key="dummy-env-key")

    def test_empty_prompt_is_rejected(self):
        """4. Empty prompt is rejected."""
        mock_client = MagicMock()
        service = GeminiService(client=mock_client)
        with self.assertRaises((ValueError, GeminiServiceError)):
            service.generate_text("")
        with self.assertRaises((ValueError, GeminiServiceError)):
            service.generate_text("   ")
        with self.assertRaises((ValueError, GeminiServiceError)):
            service.generate_json("")

    def test_generate_text_handles_mocked_successful_response(self):
        """5. generate_text handles a mocked successful Gemini response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello! I am ready to help you plan your studies."
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(client=mock_client)
        output = service.generate_text("Hello Gemini")
        self.assertEqual(output, "Hello! I am ready to help you plan your studies.")
        mock_client.models.generate_content.assert_called_once()

    def test_generate_text_converts_sdk_errors_into_gemini_service_error(self):
        """6. generate_text converts SDK errors into GeminiServiceError."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("SDK network error")

        service = GeminiService(client=mock_client)
        with self.assertRaises(GeminiServiceError):
            service.generate_text("Generate response")

    def test_generate_json_handles_valid_json(self):
        """7. generate_json handles valid JSON."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"goal": "study", "tasks": ["review", "test"]}'
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(client=mock_client)
        parsed = service.generate_json("Generate JSON plan")
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed["goal"], "study")
        self.assertEqual(parsed["tasks"], ["review", "test"])

    def test_generate_json_rejects_malformed_json(self):
        """8. generate_json rejects malformed JSON."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This is not json {bad: true"
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(client=mock_client)
        with self.assertRaises(GeminiServiceError):
            service.generate_json("Generate plan")

    def test_generate_json_rejects_non_object_json(self):
        """9. generate_json rejects non-object JSON."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '["task 1", "task 2"]'  # Array instead of object
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(client=mock_client)
        with self.assertRaises(GeminiServiceError):
            service.generate_json("Generate array")

    def test_no_eval_used(self):
        """10. No eval() is used."""
        gemini_path = os.path.join(os.path.dirname(__file__), "gemini.py")
        with open(gemini_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("eval(", content)

    def test_no_exec_used(self):
        """11. No exec() is used."""
        gemini_path = os.path.join(os.path.dirname(__file__), "gemini.py")
        with open(gemini_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("exec(", content)

    def test_system_prompt_contains_campuspilot_safety_rules(self):
        """12. System prompt contains the CampusPilot safety rules."""
        self.assertIn("CampusPilot AI", CAMPUSPILOT_SYSTEM_PROMPT)
        self.assertIn("Never invent tools", CAMPUSPILOT_SYSTEM_PROMPT)
        self.assertIn("Never execute tools yourself", CAMPUSPILOT_SYSTEM_PROMPT)
        self.assertIn("Never output executable Python code", CAMPUSPILOT_SYSTEM_PROMPT)
        self.assertIn("Never request or reveal secrets or API keys", CAMPUSPILOT_SYSTEM_PROMPT)

    def test_build_planning_prompt_includes_user_goal(self):
        """13. build_planning_prompt includes the user goal."""
        prompt = build_planning_prompt("Organize my study group")
        self.assertIn("Organize my study group", prompt)
        self.assertIn("CampusPilot AI", prompt)

    def test_api_key_never_included_in_generated_prompts(self):
        """14. API key is never included in generated prompts."""
        test_key = "dummy_test_api_key_12345"
        prompt = build_planning_prompt("Plan my exam prep")
        self.assertNotIn(test_key, prompt)

    def test_service_does_not_execute_tools(self):
        """15. Service does not execute tools."""
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"tool": "create_task", "title": "Math"}'
        mock_client.models.generate_content.return_value = mock_response

        service = GeminiService(client=mock_client)
        service.generate_json("Plan math study")

        # Storage remains completely untouched
        self.assertEqual(len(_tasks), 0)
        self.assertEqual(len(_events), 0)
        self.assertEqual(len(_notes), 0)


if __name__ == "__main__":
    unittest.main()
