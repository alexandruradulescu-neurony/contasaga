from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from documente.models import Document
from documente.services import (
    STARI_DOCUMENT,
    TRANZITII_DOCUMENT,
    TranzitieDocumentInvalida,
    poate_anula_document,
    poate_comenta_document,
    poate_incarca_documente,
    poate_reclasifica_document,
    poate_trimite_document,
    poate_verifica_documente,
    stare_urmatoare_document,
    trimite_documente_in_lot,
)

ROLURI = (
    "superuser_platforma",
    "admin_cabinet",
    "contabil_coordonator",
    "contabil",
    "client_admin",
    "client_operator",
)


class DocumentAuthorizationTests(SimpleTestCase):
    def _user(self, role, *, pk=None, active=True):
        return SimpleNamespace(
            is_authenticated=True,
            is_active=active,
            rol=role,
            pk=pk or uuid4(),
        )

    def test_upload_role_matrix(self):
        allowed = {"contabil", "contabil_coordonator", "client_admin", "client_operator"}
        for role in ROLURI:
            with self.subTest(role=role):
                self.assertIs(poate_incarca_documente(self._user(role)), role in allowed)

    def test_accounting_review_role_matrix(self):
        allowed = {"contabil", "contabil_coordonator"}
        for role in ROLURI:
            with self.subTest(role=role):
                self.assertIs(poate_verifica_documente(self._user(role)), role in allowed)

    def test_submit_requires_both_ownership_and_current_upload_role(self):
        author_id = uuid4()
        document = SimpleNamespace(incarcat_de_id=author_id)
        allowed = {"contabil", "contabil_coordonator", "client_admin", "client_operator"}
        for role in ROLURI:
            with self.subTest(role=role):
                self.assertIs(
                    poate_trimite_document(self._user(role, pk=author_id), document),
                    role in allowed,
                )

    def test_every_document_state_action_pair(self):
        for action, transitions in TRANZITII_DOCUMENT.items():
            for state in STARI_DOCUMENT:
                with self.subTest(action=action, state=state):
                    if state in transitions:
                        self.assertEqual(
                            stare_urmatoare_document(state, action),
                            transitions[state],
                        )
                    else:
                        with self.assertRaises(TranzitieDocumentInvalida):
                            stare_urmatoare_document(state, action)

    def test_cancellation_role_and_ownership_matrix(self):
        author_id = uuid4()
        document = SimpleNamespace(incarcat_de_id=author_id)
        for state in STARI_DOCUMENT:
            document.stare = state
            for role in ROLURI:
                user = self._user(role, pk=author_id if role == "client_operator" else uuid4())
                expected = False
                if state == Document.Stare.DRAFT:
                    expected = user.pk == author_id
                elif state == Document.Stare.IN_VERIFICARE:
                    expected = role in {"contabil", "contabil_coordonator"}
                elif state in {Document.Stare.TRIMIS, Document.Stare.NECESITA_CLARIFICARI}:
                    expected = role in {
                        "contabil",
                        "contabil_coordonator",
                        "client_admin",
                        "client_operator",
                    }
                with self.subTest(state=state, role=role):
                    self.assertIs(poate_anula_document(user, document), expected)

        document.stare = Document.Stare.TRIMIS
        self.assertFalse(
            poate_anula_document(self._user("client_operator"), document),
        )

    def test_reclassification_role_and_ownership_matrix(self):
        author_id = uuid4()
        document = SimpleNamespace(incarcat_de_id=author_id)
        for state in STARI_DOCUMENT:
            document.stare = state
            for role in ROLURI:
                user = self._user(role, pk=author_id if role == "client_operator" else uuid4())
                expected = False
                if state == Document.Stare.DRAFT:
                    expected = user.pk == author_id
                elif state in {
                    Document.Stare.TRIMIS,
                    Document.Stare.IN_VERIFICARE,
                    Document.Stare.NECESITA_CLARIFICARI,
                }:
                    expected = role in {"contabil", "contabil_coordonator"}
                with self.subTest(state=state, role=role):
                    self.assertIs(poate_reclasifica_document(user, document), expected)

    def test_comments_are_blocked_for_closed_or_final_documents(self):
        document = SimpleNamespace(
            stare=Document.Stare.TRIMIS,
            sters_la=None,
            perioada_contabila=SimpleNamespace(stare="deschisa"),
        )
        user = self._user("client_operator")
        self.assertTrue(poate_comenta_document(user, document))

        document.perioada_contabila.stare = "inchisa"
        self.assertFalse(poate_comenta_document(user, document))
        document.perioada_contabila.stare = "deschisa"

        for stare in (Document.Stare.ANULAT, Document.Stare.ARHIVAT):
            document.stare = stare
            with self.subTest(stare=stare):
                self.assertFalse(poate_comenta_document(user, document))

    def test_bulk_submission_has_a_bounded_series_size(self):
        with self.assertRaises(TranzitieDocumentInvalida):
            trimite_documente_in_lot(document_ids=[], actor=None, context=None)
        with self.assertRaises(TranzitieDocumentInvalida):
            trimite_documente_in_lot(
                document_ids=[uuid4() for _ in range(501)],
                actor=None,
                context=None,
            )
