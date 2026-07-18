from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from notificari.context_processors import notificari_necitite
from notificari.management.commands.send_deadline_reminders import (
    eticheta_reminder,
    parseaza_data,
)
from notificari.services import (
    DestinatarNotificare,
    _livreaza,
    cheie_deduplicare,
    normalizeaza_destinatari,
    trimite_email_invitatie,
    trimite_email_notificare,
)


class NotificationServiceTests(SimpleTestCase):
    def test_recipient_normalization_deduplicates_and_excludes_actor(self):
        actor_id = uuid4()
        recipient_id = uuid4()
        actor = DestinatarNotificare(actor_id, "actor@example.test", "Actor")
        recipient = DestinatarNotificare(recipient_id, "client@example.test", "Client")
        rezultat = normalizeaza_destinatari(
            [actor, recipient, recipient],
            exclude_id=actor_id,
        )
        self.assertEqual(rezultat, (recipient,))

    def test_deduplication_key_is_stable_and_event_scoped(self):
        date = {
            "tip": "document_nou",
            "entitate_tip": "document",
            "entitate_id": uuid4(),
            "utilizator_id": uuid4(),
        }
        prima = cheie_deduplicare(**date, eveniment_id="event-1")
        repetata = cheie_deduplicare(**date, eveniment_id="event-1")
        urmatoarea = cheie_deduplicare(**date, eveniment_id="event-2")
        self.assertEqual(prima, repetata)
        self.assertNotEqual(prima, urmatoarea)
        self.assertEqual(len(prima), 64)

    @patch("notificari.services.trimite_email_notificare")
    @patch("notificari.services.Notificare.objects")
    def test_pending_email_is_attempted_but_sent_email_is_not(self, objects, trimite):
        manager = objects.using.return_value
        destinatar = DestinatarNotificare(uuid4(), "client@example.test", "Client")
        argumente = {
            "destinatari": (destinatar,),
            "tip": "necesita_clarificari",
            "entitate_tip": "document",
            "entitate_id": uuid4(),
            "mesaj": "Sunt necesare clarificări.",
            "eveniment_id": uuid4(),
            "cu_email": True,
            "subiect_email": "Clarificări",
        }

        manager.get_or_create.return_value = (
            SimpleNamespace(pk=uuid4(), email_trimis_la=None, incercari_email=0),
            True,
        )
        _livreaza(**argumente)
        self.assertEqual(trimite.call_count, 1)
        defaults = manager.get_or_create.call_args.kwargs["defaults"]
        self.assertTrue(defaults["trimite_email"])
        self.assertTrue(defaults["vizibila_in_app"])
        self.assertEqual(defaults["subiect_email"], "Clarificări")

        manager.get_or_create.return_value = (
            SimpleNamespace(pk=uuid4(), email_trimis_la=object(), incercari_email=1),
            False,
        )
        _livreaza(**argumente)
        self.assertEqual(trimite.call_count, 1)

    @patch("notificari.services.logger.exception")
    @patch("notificari.services.trimite_email_notificare")
    @patch("notificari.services.Notificare.objects")
    def test_one_delivery_failure_does_not_block_other_recipients(
        self,
        objects,
        trimite,
        log_exception,
    ):
        objects.using.return_value.get_or_create.side_effect = [
            (SimpleNamespace(pk=uuid4(), email_trimis_la=None, incercari_email=0), True),
            (SimpleNamespace(pk=uuid4(), email_trimis_la=None, incercari_email=0), True),
        ]
        trimite.side_effect = [RuntimeError("smtp indisponibil"), True]
        destinatari = (
            DestinatarNotificare(uuid4(), "unu@example.test", "Unu"),
            DestinatarNotificare(uuid4(), "doi@example.test", "Doi"),
        )
        _livreaza(
            destinatari=destinatari,
            tip="necesita_clarificari",
            entitate_tip="document",
            entitate_id=uuid4(),
            mesaj="Sunt necesare clarificări.",
            eveniment_id=uuid4(),
            cu_email=True,
            subiect_email="Clarificări",
        )
        self.assertEqual(trimite.call_count, 2)
        log_exception.assert_called_once()

    @patch("notificari.services.transaction.atomic", return_value=nullcontext())
    @patch("notificari.services.send_mail", return_value=1)
    @patch("notificari.services.Notificare.objects")
    def test_email_success_is_persisted(self, objects, send_mail, _atomic):
        notificare = SimpleNamespace(
            trimite_email=True,
            email_trimis_la=None,
            incercari_email=0,
            subiect_email="Reminder",
            mesaj="Lipsesc documente.",
            utilizator=SimpleNamespace(nume="Client", email="client@example.test"),
            eroare_email="veche",
            save=MagicMock(),
        )
        manager = objects.using.return_value
        manager.select_for_update.return_value.select_related.return_value.get.return_value = (
            notificare
        )

        self.assertTrue(trimite_email_notificare(uuid4()))
        self.assertEqual(notificare.incercari_email, 1)
        self.assertIsNotNone(notificare.email_trimis_la)
        self.assertIsNone(notificare.eroare_email)
        send_mail.assert_called_once()
        notificare.save.assert_called_once()

    @patch("notificari.services.logger.exception")
    @patch("notificari.services.transaction.atomic", return_value=nullcontext())
    @patch("notificari.services.send_mail", side_effect=RuntimeError("smtp indisponibil"))
    @patch("notificari.services.Notificare.objects")
    def test_email_failure_is_recorded_for_retry(
        self,
        objects,
        _send_mail,
        _atomic,
        log_exception,
    ):
        notificare = SimpleNamespace(
            trimite_email=True,
            email_trimis_la=None,
            incercari_email=1,
            subiect_email="Reminder",
            mesaj="Lipsesc documente.",
            utilizator=SimpleNamespace(nume="Client", email="client@example.test"),
            eroare_email=None,
            save=MagicMock(),
        )
        manager = objects.using.return_value.select_for_update.return_value
        manager.select_related.return_value.get.return_value = notificare

        self.assertFalse(trimite_email_notificare(uuid4()))
        self.assertEqual(notificare.incercari_email, 2)
        self.assertEqual(notificare.eroare_email, "smtp indisponibil")
        log_exception.assert_called_once()

    @patch("notificari.services.send_mail", return_value=1)
    def test_invitation_email_reports_success(self, send_mail):
        self.assertTrue(
            trimite_email_invitatie(
                email="invitat@example.test",
                link_acceptare="https://app.example.test/invitatie/token/",
                destinatie="Firma Test",
            )
        )
        send_mail.assert_called_once()

    @patch("notificari.services.logger.exception")
    @patch("notificari.services.send_mail", side_effect=RuntimeError("smtp indisponibil"))
    def test_invitation_email_reports_failure(self, _send_mail, log_exception):
        self.assertFalse(
            trimite_email_invitatie(
                email="invitat@example.test",
                link_acceptare="https://app.example.test/invitatie/token/",
                destinatie="Firma Test",
            )
        )
        log_exception.assert_called_once()

    def test_deadline_labels_are_only_t_minus_three_and_t(self):
        data_rulare = date(2026, 7, 14)
        self.assertEqual(eticheta_reminder(data_rulare, date(2026, 7, 14)), "T")
        self.assertEqual(eticheta_reminder(data_rulare, date(2026, 7, 17)), "T-3")
        self.assertIsNone(eticheta_reminder(data_rulare, date(2026, 7, 16)))
        self.assertEqual(parseaza_data("2026-07-14"), data_rulare)

    @patch("notificari.context_processors.Notificare.objects")
    def test_email_only_notifications_do_not_enter_unread_badge(self, objects):
        objects.filter.return_value.count.return_value = 4
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))

        rezultat = notificari_necitite(request)

        objects.filter.assert_called_once_with(
            citita=False,
            vizibila_in_app=True,
        )
        self.assertEqual(rezultat["numar_notificari_necitite"], 4)
