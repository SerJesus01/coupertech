import unittest

from fastapi.testclient import TestClient

from main import app


class PublicPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_is_public_and_describes_the_platform(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Infraestructura sencilla para hacer crecer tu producto", response.text)
        self.assertIn("Aprendizaje de idiomas", response.text)
        self.assertNotIn('type="password"', response.text)

    def test_login_keeps_the_access_form(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn('type="password"', response.text)

    def test_private_dashboard_redirects_to_login(self):
        response = self.client.get("/dashboard", follow_redirects=False)

        self.assertIn(response.status_code, (302, 303, 307, 308))
        self.assertEqual(response.headers["location"], "/login")

    def test_public_assets_are_available(self):
        for path in ("/static/public.css", "/static/public.js", "/static/favicon.svg"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main()
