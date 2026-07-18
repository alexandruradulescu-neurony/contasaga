from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import (
    ConfigurareDocumentFirma,
    ContFinanciar,
    Firma,
    FirmaContabilitate,
    Partener,
    TipDocument,
)


class FirmaContabilitateAdmin(admin.ModelAdmin):
    list_display = ("denumire", "cui", "activ", "creat_la")
    list_filter = ("activ",)
    search_fields = ("denumire", "cui")
    ordering = ("denumire",)


class FirmaAdmin(admin.ModelAdmin):
    list_display = ("denumire", "cui", "cabinet", "activa")
    list_filter = ("activa", "cabinet")
    search_fields = ("denumire", "cui")
    autocomplete_fields = ("cabinet",)
    ordering = ("denumire",)


platform_admin_site.register(FirmaContabilitate, FirmaContabilitateAdmin)
platform_admin_site.register(Firma, FirmaAdmin)


class TipDocumentAdmin(admin.ModelAdmin):
    list_display = ("cod", "denumire", "categorie", "necesita_cont_financiar", "activ")
    search_fields = ("cod", "denumire")
    ordering = ("denumire",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


class ConfigurareDocumentFirmaAdmin(admin.ModelAdmin):
    list_display = ("firma", "tip_document", "obligatoriu", "frecventa", "activ")
    list_filter = ("obligatoriu", "frecventa", "activ")
    search_fields = ("firma__denumire", "tip_document__denumire")


class ContFinanciarAdmin(admin.ModelAdmin):
    list_display = ("denumire", "firma", "tip", "moneda", "activ")
    list_filter = ("tip", "activ")
    search_fields = ("denumire", "iban", "firma__denumire")


platform_admin_site.register(TipDocument, TipDocumentAdmin)
platform_admin_site.register(ConfigurareDocumentFirma, ConfigurareDocumentFirmaAdmin)
platform_admin_site.register(ContFinanciar, ContFinanciarAdmin)
platform_admin_site.register(Partener)
