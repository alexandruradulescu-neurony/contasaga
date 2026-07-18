from django.urls import path

import conturi.admin  # noqa: F401, E402
from config.admin_site import platform_admin_site

urlpatterns = [path("admin/", platform_admin_site.urls)]
