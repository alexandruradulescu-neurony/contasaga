from types import SimpleNamespace

from django.test import SimpleTestCase

from firme.services import poate_administra_firme, poate_crea_parteneri


class AdministrareFirmeAuthorizationTests(SimpleTestCase):
    def test_only_accounting_firm_admin_can_manage_companies(self):
        asteptari = {
            "superuser_platforma": False,
            "admin_cabinet": True,
            "contabil_coordonator": False,
            "contabil": False,
            "client_admin": False,
            "client_operator": False,
        }

        for rol, asteptat in asteptari.items():
            with self.subTest(rol=rol):
                utilizator = SimpleNamespace(
                    is_authenticated=True,
                    is_active=True,
                    rol=rol,
                    cabinet_id="cabinet-id"
                    if rol
                    in {
                        "admin_cabinet",
                        "contabil_coordonator",
                        "contabil",
                    }
                    else None,
                )
                self.assertIs(poate_administra_firme(utilizator), asteptat)

    def test_inactive_admin_cannot_manage_companies(self):
        utilizator = SimpleNamespace(
            is_authenticated=True,
            is_active=False,
            rol="admin_cabinet",
            cabinet_id="cabinet-id",
        )
        self.assertFalse(poate_administra_firme(utilizator))


class PartenerAuthorizationTests(SimpleTestCase):
    def test_only_accountants_can_create_partners(self):
        for rol in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            utilizator = SimpleNamespace(
                is_authenticated=True,
                is_active=True,
                rol=rol,
            )
            with self.subTest(rol=rol):
                self.assertIs(
                    poate_crea_parteneri(utilizator),
                    rol in {"contabil", "contabil_coordonator"},
                )
