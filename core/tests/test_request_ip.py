from django.test import RequestFactory, SimpleTestCase, override_settings

from core.audit import context_audit_din_request
from core.request_ip import ip_client


class ClientIpTests(SimpleTestCase):
    def test_remote_address_is_used_by_default_and_written_to_audit(self):
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.44")
        self.assertEqual(ip_client(request), "192.0.2.44")
        self.assertEqual(context_audit_din_request(request).ip_address, "192.0.2.44")

    @override_settings(CLIENT_IP_HEADER="HTTP_X_FORWARDED_FOR")
    def test_explicit_trusted_header_uses_first_valid_address(self):
        request = RequestFactory().get(
            "/",
            REMOTE_ADDR="10.0.0.10",
            HTTP_X_FORWARDED_FOR="198.51.100.15, 10.0.0.10",
        )
        self.assertEqual(ip_client(request), "198.51.100.15")
