from types import SimpleNamespace

from django.test import SimpleTestCase

from conturi.allocations import poate_gestiona_alocari
from conturi.invitation_forms import AcceptareInvitatieForm
from conturi.invitations import poate_gestiona_invitatii, roluri_permise_pentru


class InvitationAuthorizationTests(SimpleTestCase):
    def _user(self, role, *, cabinet_id=None, active=True):
        return SimpleNamespace(
            is_authenticated=True,
            is_active=active,
            rol=role,
            cabinet_id=cabinet_id,
        )

    def test_management_role_matrix(self):
        asteptari = {
            "superuser_platforma": False,
            "admin_cabinet": True,
            "contabil_coordonator": False,
            "contabil": False,
            "client_admin": True,
            "client_operator": False,
        }
        for rol, asteptat in asteptari.items():
            with self.subTest(rol=rol):
                utilizator = self._user(
                    rol,
                    cabinet_id="accounting-firm" if rol == "admin_cabinet" else None,
                )
                self.assertIs(poate_gestiona_invitatii(utilizator), asteptat)

    def test_accounting_firm_admin_invitation_roles(self):
        utilizator = self._user("admin_cabinet", cabinet_id="accounting-firm")
        self.assertEqual(
            roluri_permise_pentru(utilizator),
            {
                "admin_cabinet",
                "contabil_coordonator",
                "contabil",
                "client_admin",
                "client_operator",
            },
        )

    def test_client_admin_can_invite_only_operator(self):
        utilizator = self._user("client_admin")
        self.assertEqual(roluri_permise_pentru(utilizator), {"client_operator"})

    def test_only_accounting_firm_admin_manages_internal_assignments(self):
        for rol in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(rol=rol):
                utilizator = self._user(
                    rol,
                    cabinet_id="accounting-firm"
                    if rol
                    in {
                        "admin_cabinet",
                        "contabil_coordonator",
                        "contabil",
                    }
                    else None,
                )
                self.assertIs(poate_gestiona_alocari(utilizator), rol == "admin_cabinet")

    def test_invitation_password_is_validated_against_invited_identity(self):
        invitatie = SimpleNamespace(
            email="ana.popescu@example.test",
            rol="client_admin",
        )
        form = AcceptareInvitatieForm(
            {
                "nume": "Ana Popescu",
                "telefon": "",
                "password1": "ana.popescu@example.test",
                "password2": "ana.popescu@example.test",
            },
            invitatie=invitatie,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)
