from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from firme.configuration_services import salveaza_configurare


class SalvareConfigurareTests(SimpleTestCase):
    @patch("firme.configuration_services._audit")
    @patch("firme.configuration_services._verifica")
    @patch("firme.configuration_services.transaction.atomic", return_value=nullcontext())
    @patch("firme.configuration_services.ConfigurareDocumentFirma.objects.update_or_create")
    def test_creator_is_only_set_when_configuration_is_created(
        self,
        update_or_create,
        _atomic,
        _verifica,
        _audit,
    ):
        configurare = SimpleNamespace(
            pk="config-id",
            activ=False,
            obligatoriu=False,
            creat_de_id="creator-original",
        )
        update_or_create.return_value = (configurare, False)
        actor = SimpleNamespace(pk="actor-curent")
        firma = SimpleNamespace(pk="firma-id")
        tip_document = SimpleNamespace(pk="tip-id", cod="factura")
        date = {"activ": False, "obligatoriu": False, "frecventa": "lunar"}

        salveaza_configurare(
            actor=actor,
            firma=firma,
            tip_document=tip_document,
            date=date,
            context=SimpleNamespace(ip_address=None, user_agent=""),
        )

        update_or_create.assert_called_once_with(
            firma=firma,
            tip_document=tip_document,
            defaults=date,
            create_defaults={**date, "creat_de_id": actor.pk},
        )
        self.assertEqual(configurare.creat_de_id, "creator-original")
