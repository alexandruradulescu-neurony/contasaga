from collections.abc import Callable

from django.db import connections, transaction
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse


class RLSMiddleware:
    """Leagă identitatea Django de politicile PostgreSQL pentru un request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.get_response(request)

        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.utilizator_id', %s, true)",
                    [str(request.user.pk)],
                )

            response = self.get_response(request)
            if isinstance(response, StreamingHttpResponse) and not getattr(
                response,
                "rls_safe_streaming",
                False,
            ):
                transaction.set_rollback(True, using="default")
                raise RuntimeError("StreamingHttpResponse autentificat nu este suportat")
            if response.status_code >= 400:
                transaction.set_rollback(True, using="default")

        return response
