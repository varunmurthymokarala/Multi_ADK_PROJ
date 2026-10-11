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

    def test_dropdown_lists_three_restaurants(self):
        tenants = self.client.get("/api/tenants")
        self.assertEqual(tenants.status_code, 200)
        ids = [t["id"] for t in tenants.json()]
        self.assertEqual(len(ids), 3)
        self.assertIn("saffron-spice", ids)
        self.assertIn("sakura-sushi", ids)
        self.assertIn("taco-cantina", ids)

        # Full house menu stays as-is; sample tenants ship with 10 items each.
        expected_counts = {"saffron-spice": 41, "sakura-sushi": 10, "taco-cantina": 10}
        for tenant_id in ids:
            with self.subTest(tenant=tenant_id):
                cfg = next(t for t in tenants.json() if t["id"] == tenant_id)
                # Branding fields the header/footer JS applies on dropdown switch.
                for key in ("name", "tagline", "blurb", "address", "phone",
                            "hours_text", "open_till", "eta_minutes"):
                    self.assertIn(key, cfg)
                menu = self.client.get(f"/api/menu/{tenant_id}")
                self.assertEqual(menu.status_code, 200)
                self.assertEqual(len(menu.json()["items"]), expected_counts[tenant_id])

    def test_forgot_reset_password_only_for_existing_gmail_accounts(self):
        import uuid as _uuid
        gmail = f"varun.test-{_uuid.uuid4().hex[:8]}@gmail.com"
        nongmail = f"tester-{_uuid.uuid4().hex[:8]}@example.com"
        for email in (gmail, nongmail):
            reg = self.client.post("/api/auth/register", json={
                "name": "Reset Tester", "email": email, "password": "oldpass123"})
            self.assertEqual(reg.status_code, 200)

        # Non-Gmail address is rejected even though the account exists.
        bad_domain = self.client.post("/api/auth/forgot", json={"email": nongmail})
        self.assertEqual(bad_domain.status_code, 400)
        self.assertIn("Gmail", bad_domain.json()["detail"])

        # Gmail address with no account is rejected.
        ghost = self.client.post("/api/auth/forgot", json={
            "email": f"nobody-{_uuid.uuid4().hex[:8]}@gmail.com"})
        self.assertEqual(ghost.status_code, 400)
        self.assertIn("No account exists", ghost.json()["detail"])

        # Existing Gmail account gets a code (dev mode returns it inline).
        sent = self.client.post("/api/auth/forgot", json={"email": gmail})
        self.assertEqual(sent.status_code, 200)
        code = sent.json()["dev_code"]
        self.assertTrue(code.isdigit() and len(code) == 6)

        # Wrong code is rejected; password is unchanged.
        wrong = self.client.post("/api/auth/reset", json={
            "email": gmail, "code": "000000" if code != "000000" else "111111",
            "password": "newpass123"})
        self.assertEqual(wrong.status_code, 400)
        still_old = self.client.post("/api/auth/login", json={
            "email": gmail, "password": "oldpass123"})
        self.assertEqual(still_old.status_code, 200)

        # Correct code sets the new password and invalidates the code reuse.
        ok = self.client.post("/api/auth/reset", json={
            "email": gmail, "code": code, "password": "newpass123"})
        self.assertEqual(ok.status_code, 200)
        reuse = self.client.post("/api/auth/reset", json={
            "email": gmail, "code": code, "password": "another123"})
        self.assertEqual(reuse.status_code, 400)
        old_login = self.client.post("/api/auth/login", json={
            "email": gmail, "password": "oldpass123"})
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post("/api/auth/login", json={
            "email": gmail, "password": "newpass123"})
        self.assertEqual(new_login.status_code, 200)

    def test_global_concierge_recommends_across_restaurants(self):
        # Greeting lists all restaurants, no forced pick.
        greeting = self.client.post("/api/chat/global", json={"message": "hi"})
        self.assertEqual(greeting.status_code, 200)
        body = greeting.json()
        for name in ("Saffron", "Sakura", "Taco"):
            self.assertIn(name, body["text"])
        self.assertIsNone(body["restaurant_id"])
        self.assertEqual(len(body["restaurants"]), 3)

        # A dish name routes to the restaurant that has it.
        butter = self.client.post("/api/chat/global", json={"message": "butter chicken"})
        self.assertEqual(butter.json()["restaurant_id"], "saffron-spice")
        self.assertIn("18.50", butter.json()["text"])

        # A cuisine routes even when no dish contains the word.
        sushi = self.client.post("/api/chat/global", json={"message": "sushi"})
        self.assertEqual(sushi.json()["restaurant_id"], "sakura-sushi")
        self.assertIn("Sakura Sushi", sushi.json()["text"])

        tacos = self.client.post("/api/chat/global", json={"message": "tacos"})
        self.assertEqual(tacos.json()["restaurant_id"], "taco-cantina")

        # Cross-restaurant preference: several hits, no single restaurant.
        vegan = self.client.post("/api/chat/global", json={"message": "vegan under $8"})
        self.assertEqual(vegan.status_code, 200)
        self.assertIn("Papad", vegan.json()["text"])
        self.assertIsNone(vegan.json()["restaurant_id"])

    def test_register_login_and_me_flow(self):
        import uuid as _uuid
        email = f"tester-{_uuid.uuid4().hex[:8]}@example.com"
        reg = self.client.post("/api/auth/register", json={
            "name": "Tester", "email": email, "password": "secret123"})
        self.assertEqual(reg.status_code, 200)
        token = reg.json()["token"]
        self.assertEqual(reg.json()["user"]["email"], email)

        dup = self.client.post("/api/auth/register", json={
            "name": "Tester", "email": email, "password": "secret123"})
        self.assertEqual(dup.status_code, 400)

        login = self.client.post("/api/auth/login", json={
            "email": email, "password": "secret123"})
        self.assertEqual(login.status_code, 200)

        bad = self.client.post("/api/auth/login", json={
            "email": email, "password": "wrong"})
        self.assertEqual(bad.status_code, 401)

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], email)

        cfg = self.client.get("/api/auth/config")
        self.assertIn("google_client_id", cfg.json())

    def test_landing_pages(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/app").status_code, 200)


if __name__ == "__main__":
    unittest.main()
