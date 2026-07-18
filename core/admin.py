from django.contrib import admin

from config.admin_site import platform_admin_site

from .models import AuditLog, IstoricStare


class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("creat_la", "entitate_tip", "actiune", "firma_id", "utilizator_id")
    list_filter = ("entitate_tip", "actiune")
    search_fields = ("entitate_id", "firma_id", "utilizator_id")
    ordering = ("-creat_la",)
    readonly_fields = (
        "id",
        "firma_id",
        "utilizator_id",
        "entitate_tip",
        "entitate_id",
        "actiune",
        "date_vechi",
        "date_noi",
        "ip_address",
        "user_agent",
        "creat_la",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


platform_admin_site.register(AuditLog, AuditLogAdmin)


class IstoricStareAdmin(admin.ModelAdmin):
    list_display = ("creat_la", "entitate_tip", "stare_veche", "stare_noua", "firma_id")
    list_filter = ("entitate_tip", "stare_noua")
    ordering = ("-creat_la",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


platform_admin_site.register(IstoricStare, IstoricStareAdmin)
