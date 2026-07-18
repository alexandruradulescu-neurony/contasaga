from django.contrib.admin import AdminSite
from django.http import HttpRequest


class PlatformAdminSite(AdminSite):
    site_header = "Conta Saga — administrare platformă"
    site_title = "Conta Saga Admin"
    index_title = "Platformă"

    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        return bool(user.is_active and user.is_superuser)


platform_admin_site = PlatformAdminSite(name="platform_admin")
