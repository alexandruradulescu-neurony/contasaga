from types import SimpleNamespace

from django.test import SimpleTestCase

from logistica.forms import DigitizareForm, ProgramarePredareForm
from logistica.models import PredareDocumente
from logistica.services import (
    TRANZITII_DIGITIZARE,
    TRANZITII_PREDARI,
    EroareLogistica,
    poate_gestiona_predari,
    poate_programa_predare,
    stare_urmatoare_digitizare,
    stare_urmatoare_predare,
)


class LogisticsWorkflowTests(SimpleTestCase):
    def _user(self, role, *, active=True):
        return SimpleNamespace(
            is_authenticated=True,
            is_active=active,
            rol=role,
        )

    def test_scheduling_role_matrix(self):
        permise = {"contabil", "contabil_coordonator", "client_admin", "client_operator"}
        for rol in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(rol=rol):
                self.assertIs(poate_programa_predare(self._user(rol)), rol in permise)
        self.assertFalse(poate_programa_predare(self._user("client_admin", active=False)))

    def test_transition_role_matrix(self):
        permise = {"contabil", "contabil_coordonator"}
        for rol in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(rol=rol):
                self.assertIs(poate_gestiona_predari(self._user(rol)), rol in permise)

    def test_every_state_action_pair(self):
        for actiune, tranzitii in TRANZITII_PREDARI.items():
            for stare in PredareDocumente.Status.values:
                with self.subTest(actiune=actiune, stare=stare):
                    if stare in tranzitii:
                        self.assertEqual(
                            stare_urmatoare_predare(stare, actiune),
                            tranzitii[stare],
                        )
                    else:
                        with self.assertRaises(EroareLogistica):
                            stare_urmatoare_predare(stare, actiune)

    def test_physical_handoff_requires_person_boxes_and_date(self):
        formular = ProgramarePredareForm(
            {
                "metoda": PredareDocumente.Metoda.CURIER,
                "predat_de": "",
                "numar_cutii": "0",
                "data_programata": "",
                "observatii": "",
            }
        )
        self.assertFalse(formular.is_valid())
        self.assertEqual(
            set(formular.errors),
            {"predat_de", "numar_cutii", "data_programata"},
        )

    def test_digital_handoff_discards_physical_fields(self):
        formular = ProgramarePredareForm(
            {
                "metoda": PredareDocumente.Metoda.EXCLUSIV_DIGITAL,
                "predat_de": "Client",
                "numar_cutii": "4",
                "data_programata": "2026-07-15T09:30",
                "observatii": "Totul este în platformă.",
            }
        )
        self.assertTrue(formular.is_valid(), formular.errors)
        self.assertEqual(formular.cleaned_data["numar_cutii"], 0)
        self.assertIsNone(formular.cleaned_data["data_programata"])

    def test_every_digitization_state_action_pair(self):
        for actiune, tranzitii in TRANZITII_DIGITIZARE.items():
            for stare in PredareDocumente.StatusDigitizare.values:
                with self.subTest(actiune=actiune, stare=stare):
                    if stare in tranzitii:
                        self.assertEqual(
                            stare_urmatoare_digitizare(stare, actiune),
                            tranzitii[stare],
                        )
                    else:
                        with self.assertRaises(EroareLogistica):
                            stare_urmatoare_digitizare(stare, actiune)

    def test_digitization_estimate_is_optional_but_positive(self):
        self.assertTrue(DigitizareForm({"numar_documente_estimat": ""}).is_valid())
        self.assertTrue(DigitizareForm({"numar_documente_estimat": "120"}).is_valid())
        self.assertFalse(DigitizareForm({"numar_documente_estimat": "0"}).is_valid())
