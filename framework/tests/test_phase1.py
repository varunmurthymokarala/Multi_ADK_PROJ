import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.main import app
from core.chat import reply


class PhaseOneFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_menu_chat_cart_and_order_flow(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        menu = self.client.get("/api/menu/saffron-spice")
        self.assertEqual(menu.status_code, 200)
        self.assertEqual(len(menu.json()["items"]), 41)

        menu_chat = self.client.post("/api/chat/saffron-spice", json={"message": "vegan options"})
        self.assertEqual(menu_chat.status_code, 200)
        session_id = menu_chat.json()["session_id"]
        self.assertIn("Chana Masala", menu_chat.json()["text"])

        add = self.client.post("/api/chat/saffron-spice", json={"session_id": session_id, "message": "add 2 Chicken Biryani"})
        self.assertEqual(add.status_code, 200)
        self.assertEqual(add.json()["total"], 39.0)

        order = self.client.post("/api/orders/saffron-spice", json={"session_id": session_id})
        self.assertEqual(order.status_code, 200)
        self.assertEqual(order.json()["status"], "pending_payment")
        self.assertEqual(order.json()["total"], 39.0)

    def test_open_ended_question_uses_grounded_ollama_prompt(self):
        with patch("core.chat.ollama_chat", new=AsyncMock(return_value="The Vegetable Biryani is a great choice.")) as model:
            result = asyncio.run(reply("saffron-spice", "llm-test", "What should I eat tonight?"))

        self.assertEqual(result["source"], "ollama")
        self.assertIn("Vegetable Biryani", result["text"])
        prompt = model.await_args.args[0][0]["content"]
        self.assertIn("$16.00", prompt)
        self.assertIn("Do not invent", prompt)

    def test_unavailable_dish_does_not_match_a_substring_in_the_menu(self):
        result = self.client.post("/api/chat/saffron-spice", json={"message": "Can I have one sushi?"})

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["source"], "deterministic")
        self.assertIn("Sushi is not available", result.json()["text"])
        self.assertNotIn("Mango Lassi", result.json()["text"])


if __name__ == "__main__":
    unittest.main()
