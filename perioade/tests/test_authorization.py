from types import SimpleNamespace

from django.test import SimpleTestCase

from perioade.services import (
    TRANZITII_PERIOADA,
    TranzitieInvalida,
    poate_actualiza_checklist,
    poate_confirma_perioada,
    poate_deschide_perioade,
    poate_procesa_perioada,
    poate_redeschide_perioada,
    stare_urmatoare,
)


class PeriodAuthorizationTests(SimpleTestCase):
    def _user(self, role, active=True):
        return SimpleNamespace(is_authenticated=True, is_active=active, rol=role)

    def test_open_period_role_matrix(self):
        allowed = {"contabil", "contabil_coordonator"}
        for role in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(role=role):
                self.assertIs(poate_deschide_perioade(self._user(role)), role in allowed)

    def test_checklist_update_role_matrix(self):
        allowed = {"contabil", "contabil_coordonator", "client_admin"}
        for role in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(role=role):
                self.assertIs(poate_actualiza_checklist(self._user(role)), role in allowed)

    def test_transition_role_matrix(self):
        roles = (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        )
        for role in roles:
            user = self._user(role)
            with self.subTest(role=role):
                self.assertIs(poate_confirma_perioada(user), role == "client_admin")
                self.assertIs(
                    poate_procesa_perioada(user),
                    role in {"contabil", "contabil_coordonator"},
                )
                self.assertIs(
                    poate_redeschide_perioada(user),
                    role in {"admin_cabinet", "contabil_coordonator"},
                )

    def test_every_period_state_action_pair(self):
        stari = {
            "deschisa",
            "documente_incomplete",
            "gata_pentru_verificare",
            "in_lucru",
            "inchidere_in_curs",
            "inchisa",
        }
        for actiune, tranzitii in TRANZITII_PERIOADA.items():
            for stare in stari:
                with self.subTest(actiune=actiune, stare=stare):
                    if stare in tranzitii:
                        self.assertEqual(stare_urmatoare(stare, actiune), tranzitii[stare])
                    else:
                        with self.assertRaises(TranzitieInvalida):
                            stare_urmatoare(stare, actiune)

    def test_closure_enters_locked_background_state(self):
        self.assertEqual(stare_urmatoare("in_lucru", "inchide"), "inchidere_in_curs")
