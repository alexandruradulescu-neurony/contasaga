from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import (
    AnalizaFisierInbox,
    ArhivaLunara,
    Comentariu,
    DerivareFisierInbox,
    Document,
    ExtractieStructurataDocument,
    FisierArhivaLunara,
    FisierDocument,
    FisierInbox,
    IntentieUpload,
    LotIncarcare,
    PaginaFisierInbox,
)


class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "tip_document",
        "firma",
        "perioada_contabila",
        "predare_documente",
        "stare",
        "incarcat_de",
        "creat_la",
    )
    list_filter = ("stare", "tip_document")
    search_fields = ("serie", "numar", "note")
    readonly_fields = ("creat_la", "actualizat_la")


class FisierDocumentAdmin(admin.ModelAdmin):
    list_display = ("nume_original", "document", "stare_procesare", "versiune", "activ")
    list_filter = ("stare_procesare", "activ")
    readonly_fields = ("storage_key", "checksum", "incarcat_la")


class ComentariuAdmin(admin.ModelAdmin):
    list_display = ("document", "perioada_contabila", "utilizator", "creat_la")
    readonly_fields = ("creat_la",)


class IntentieUploadAdmin(admin.ModelAdmin):
    list_display = ("nume_original", "document", "utilizator", "expira_la", "folosita_la")
    readonly_fields = ("storage_key", "expira_la", "folosita_la", "creat_la")


class LotIncarcareAdmin(admin.ModelAdmin):
    list_display = (
        "creat_la",
        "firma",
        "perioada_contabila",
        "status",
        "numar_fisiere_declarat",
        "creat_de",
    )
    list_filter = ("status",)
    readonly_fields = (
        "firma",
        "perioada_contabila",
        "creat_de",
        "status",
        "numar_fisiere_declarat",
        "dimensiune_totala_declarata",
        "nota",
        "finalizat_la",
        "creat_la",
        "actualizat_la",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class FisierInboxAdmin(admin.ModelAdmin):
    list_display = ("nume_original", "lot", "status", "dimensiune_bytes", "incarcat_la")
    list_filter = ("status", "mime_type")
    readonly_fields = (
        "lot",
        "firma",
        "perioada_contabila",
        "incarcat_de",
        "temp_storage_key",
        "storage_key",
        "nume_original",
        "mime_type",
        "dimensiune_declarata",
        "dimensiune_bytes",
        "checksum",
        "status",
        "eroare",
        "expira_la",
        "incarcat_la",
        "creat_la",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class AnalizaFisierInboxAdmin(admin.ModelAdmin):
    list_display = (
        "fisier_inbox",
        "status",
        "status_revizuire",
        "provider",
        "model",
        "incredere",
        "revizuita_la",
    )
    list_filter = ("status", "status_revizuire", "provider")
    readonly_fields = tuple(field.name for field in AnalizaFisierInbox._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class PaginaFisierInboxAdmin(admin.ModelAdmin):
    list_display = ("fisier_inbox", "numar_pagina", "metoda", "creat_la")
    list_filter = ("metoda",)
    readonly_fields = tuple(field.name for field in PaginaFisierInbox._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class DerivareFisierInboxAdmin(admin.ModelAdmin):
    list_display = (
        "fisier_inbox",
        "document",
        "pagina_start",
        "pagina_sfarsit",
        "metoda",
        "creat_la",
    )
    readonly_fields = tuple(field.name for field in DerivareFisierInbox._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ReadOnlyTraceAdmin(admin.ModelAdmin):
    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ExtractieStructurataDocumentAdmin(ReadOnlyTraceAdmin):
    list_display = ("document", "status", "status_revizuire", "provider", "creat_la")
    list_filter = ("status", "status_revizuire", "provider")
    readonly_fields = tuple(field.name for field in ExtractieStructurataDocument._meta.fields)


class ArhivaLunaraAdmin(ReadOnlyTraceAdmin):
    list_display = ("perioada_contabila", "versiune", "status", "numar_fisiere", "creat_la")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in ArhivaLunara._meta.fields)


class FisierArhivaLunaraAdmin(ReadOnlyTraceAdmin):
    list_display = ("arhiva", "ordine", "categorie", "nume_original")
    readonly_fields = tuple(field.name for field in FisierArhivaLunara._meta.fields)


platform_admin_site.register(Document, DocumentAdmin)
platform_admin_site.register(FisierDocument, FisierDocumentAdmin)
platform_admin_site.register(Comentariu, ComentariuAdmin)
platform_admin_site.register(IntentieUpload, IntentieUploadAdmin)
platform_admin_site.register(LotIncarcare, LotIncarcareAdmin)
platform_admin_site.register(FisierInbox, FisierInboxAdmin)
platform_admin_site.register(AnalizaFisierInbox, AnalizaFisierInboxAdmin)
platform_admin_site.register(PaginaFisierInbox, PaginaFisierInboxAdmin)
platform_admin_site.register(DerivareFisierInbox, DerivareFisierInboxAdmin)
platform_admin_site.register(ExtractieStructurataDocument, ExtractieStructurataDocumentAdmin)
platform_admin_site.register(ArhivaLunara, ArhivaLunaraAdmin)
platform_admin_site.register(FisierArhivaLunara, FisierArhivaLunaraAdmin)
