from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

from django.http import HttpResponse, StreamingHttpResponse
from django.test import SimpleTestCase

from core.middleware import RLSMiddleware


class RLSMiddlewareStreamingTests(SimpleTestCase):
    def _request(self):
        return SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, pk=uuid4()),
        )

    def _connection(self):
        conexiune = MagicMock()
        conexiune.cursor.return_value.__enter__.return_value = MagicMock()
        return conexiune

    @patch("core.middleware.transaction.set_rollback")
    @patch("core.middleware.transaction.atomic", return_value=nullcontext())
    def test_authenticated_generic_stream_is_rejected(self, _atomic, set_rollback):
        middleware = RLSMiddleware(lambda _request: StreamingHttpResponse(iter([b"date"])))
        with patch("core.middleware.connections", {"default": self._connection()}):
            with self.assertRaises(RuntimeError):
                middleware(self._request())
        set_rollback.assert_called_once_with(True, using="default")

    @patch("core.middleware.transaction.atomic", return_value=nullcontext())
    def test_explicit_database_free_stream_is_allowed(self, _atomic):
        def raspuns(_request):
            response = StreamingHttpResponse(iter([b"date"]))
            response.rls_safe_streaming = True
            return response

        middleware = RLSMiddleware(raspuns)
        with patch("core.middleware.connections", {"default": self._connection()}):
            response = middleware(self._request())
        self.assertTrue(response.streaming)


class RLSMiddlewareTransactionTests(SimpleTestCase):
    def _request(self, pk=None):
        return SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, pk=pk or uuid4()),
        )

    def _connection(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        return connection, cursor

    @patch("core.middleware.transaction.set_rollback")
    @patch("core.middleware.transaction.atomic", return_value=nullcontext())
    def test_every_error_response_rolls_back(self, _atomic, set_rollback):
        for status in (400, 403, 404, 500):
            with self.subTest(status=status):
                set_rollback.reset_mock()
                connection, _cursor = self._connection()
                middleware = RLSMiddleware(
                    lambda _request, response_status=status: HttpResponse(status=response_status)
                )
                with patch("core.middleware.connections", {"default": connection}):
                    response = middleware(self._request())
                self.assertEqual(response.status_code, status)
                set_rollback.assert_called_once_with(True, using="default")

    @patch("core.middleware.transaction.set_rollback")
    @patch("core.middleware.transaction.atomic", return_value=nullcontext())
    def test_successful_response_commits_normally(self, _atomic, set_rollback):
        connection, _cursor = self._connection()
        middleware = RLSMiddleware(lambda _request: HttpResponse(status=200))
        with patch("core.middleware.connections", {"default": connection}):
            middleware(self._request())
        set_rollback.assert_not_called()

    @patch("core.middleware.transaction.atomic", return_value=nullcontext())
    def test_each_request_sets_its_own_transaction_local_identity(self, _atomic):
        first_id = uuid4()
        second_id = uuid4()
        connection, cursor = self._connection()
        middleware = RLSMiddleware(lambda _request: HttpResponse(status=200))
        with patch("core.middleware.connections", {"default": connection}):
            middleware(self._request(first_id))
            middleware(self._request(second_id))
        self.assertEqual(
            cursor.execute.call_args_list,
            [
                call("SELECT set_config('app.utilizator_id', %s, true)", [str(first_id)]),
                call("SELECT set_config('app.utilizator_id', %s, true)", [str(second_id)]),
            ],
        )
