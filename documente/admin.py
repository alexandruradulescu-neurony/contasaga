from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import Comentariu, Document, FisierDocument, IntentieUpload


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


platform_admin_site.register(Document, DocumentAdmin)
platform_admin_site.register(FisierDocument, FisierDocumentAdmin)
platform_admin_site.register(Comentariu, ComentariuAdmin)
platform_admin_site.register(IntentieUpload, IntentieUploadAdmin)
