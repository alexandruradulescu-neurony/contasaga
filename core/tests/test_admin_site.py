from django.test import SimpleTestCase

from config.admin_site import platform_admin_site
from exporturi.models import Export
from logistica.models import PredareDocumente


class PlatformAdminRegistrationTests(SimpleTestCase):
    def test_operational_models_are_registered_on_platform_admin(self):
        self.assertIn(Export, platform_admin_site._registry)
        self.assertIn(PredareDocumente, platform_admin_site._registry)
