from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import CerintaDocumentPerioada, PerioadaContabila


class PerioadaContabilaAdmin(admin.ModelAdmin):
    list_display = ("firma", "luna", "an", "stare", "termen_predare")
    list_filter = ("stare", "an", "luna")
    search_fields = ("firma__denumire", "firma__cui")
    ordering = ("-an", "-luna")


class CerintaDocumentPerioadaAdmin(admin.ModelAdmin):
    list_display = ("perioada_contabila", "tip_document", "cont_financiar", "status")
    list_filter = ("status", "tip_document")
    search_fields = ("firma__denumire", "tip_document__denumire")


platform_admin_site.register(PerioadaContabila, PerioadaContabilaAdmin)
platform_admin_site.register(CerintaDocumentPerioada, CerintaDocumentPerioadaAdmin)
