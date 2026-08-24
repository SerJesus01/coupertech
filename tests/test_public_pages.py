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

    def test_public_information_pages_are_available(self):
        pages = {
            "/servicios": "Una plataforma, distintas capacidades",
            "/seguridad": "Confianza construida en cada capa",
            "/nosotros": "Tecnología fresca, seria y cercana",
            "/contacto": "Un canal directo con el equipo",
        }

        for path, expected_text in pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_text, response.text)

    def test_home_navigation_links_to_public_pages(self):
        response = self.client.get("/")

        for path in ("/servicios", "/seguridad", "/nosotros", "/contacto"):
            with self.subTest(path=path):
                self.assertIn(f'href="{path}"', response.text)


if __name__ == "__main__":
    unittest.main()
