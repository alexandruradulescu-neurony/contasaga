from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import PredareDocumente


@admin.register(PredareDocumente, site=platform_admin_site)
class PredareDocumenteAdmin(admin.ModelAdmin):
    list_display = (
        "firma",
        "perioada_contabila",
        "metoda",
        "status",
        "digitizare_status",
        "numar_cutii",
        "creat_la",
    )
    list_filter = ("metoda", "status", "digitizare_status")
    search_fields = ("firma__denumire", "predat_de")
    readonly_fields = (
        "id",
        "firma",
        "perioada_contabila",
        "metoda",
        "status",
        "predat_de",
        "preluat_de",
        "numar_cutii",
        "data_programata",
        "data_preluare",
        "data_receptie",
        "data_returnare",
        "digitizare_status",
        "numar_documente_estimat",
        "digitizare_inceputa_la",
        "digitizare_inceputa_de",
        "digitizare_finalizata_la",
        "digitizare_finalizata_de",
        "observatii",
        "creat_de",
        "creat_la",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
