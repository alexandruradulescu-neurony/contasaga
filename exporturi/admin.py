from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import Export


@admin.register(Export, site=platform_admin_site)
class ExportAdmin(admin.ModelAdmin):
    list_display = (
        "perioada_contabila",
        "solicitat_de",
        "status",
        "creat_la",
        "expira_la",
    )
    list_filter = ("status",)
    search_fields = ("firma__denumire", "solicitat_de__email")
    readonly_fields = (
        "id",
        "firma",
        "perioada_contabila",
        "solicitat_de",
        "status",
        "storage_key",
        "eroare",
        "creat_la",
        "expira_la",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
