from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from config.admin_site import platform_admin_site

from .forms import UtilizatorChangeForm, UtilizatorCreationForm
from .models import Invitatie, Utilizator, UtilizatorFirma


class UtilizatorAdmin(UserAdmin):
    add_form = UtilizatorCreationForm
    form = UtilizatorChangeForm
    model = Utilizator
    ordering = ("email",)
    list_display = ("email", "nume", "rol", "is_active", "is_superuser")
    list_filter = ("rol", "is_active", "is_superuser")
    search_fields = ("email", "nume")
    filter_horizontal = ()
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profil", {"fields": ("nume", "telefon", "rol", "firma_contabilitate")}),
        ("Stare", {"fields": ("is_active", "is_staff", "is_superuser", "last_login")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "nume",
                    "rol",
                    "firma_contabilitate",
                    "password1",
                    "password2",
                ),
            },
        ),
    )


platform_admin_site.register(Utilizator, UtilizatorAdmin)


class UtilizatorFirmaAdmin(admin.ModelAdmin):
    list_display = ("utilizator", "firma", "rol_in_firma", "data_alocare")
    search_fields = ("utilizator__email", "firma__denumire", "firma__cui")
    ordering = ("-data_alocare",)
    autocomplete_fields = ("utilizator", "firma", "alocat_de")


class InvitatieAdmin(admin.ModelAdmin):
    list_display = ("email", "rol", "firma", "cabinet", "expira_la", "acceptata_la", "anulata_la")
    search_fields = ("email",)
    ordering = ("-creat_la",)
    readonly_fields = ("token_hash", "creat_la", "acceptata_la", "anulata_la")


platform_admin_site.register(UtilizatorFirma, UtilizatorFirmaAdmin)
platform_admin_site.register(Invitatie, InvitatieAdmin)
