import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now
from django.urls import reverse


class Notificare(models.Model):
    class Tip(models.TextChoices):
        REMINDER_TERMEN = "reminder_termen", "Reminder termen"
        DOCUMENT_NOU = "document_nou", "Document nou"
        NECESITA_CLARIFICARI = "necesita_clarificari", "Necesită clarificări"
        CLARIFICARI_REZOLVATE = "clarificari_rezolvate", "Clarificări rezolvate"
        PERIOADA_CONFIRMATA = "perioada_confirmata", "Perioadă confirmată"
        PERIOADA_INCHISA = "perioada_inchisa", "Perioadă închisă"
        COMENTARIU_NOU = "comentariu_nou", "Comentariu nou"
        EXPORT_FINALIZAT = "export_finalizat", "Export finalizat"
        EROARE_PROCESARE_FISIER = "eroare_procesare_fisier", "Eroare procesare fișier"
        INVITATIE = "invitatie", "Invitație"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilizator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="utilizator_id",
        on_delete=models.PROTECT,
        related_name="notificari",
    )
    tip = models.CharField(max_length=40, choices=Tip.choices)
    entitate_tip = models.CharField(max_length=30, null=True, blank=True)  # noqa: DJ001
    entitate_id = models.UUIDField(null=True, blank=True)
    mesaj = models.CharField(max_length=500)
    cheie_deduplicare = models.CharField(max_length=64, null=True, blank=True, unique=True)
    citita = models.BooleanField(default=False)
    vizibila_in_app = models.BooleanField(default=True)
    trimite_email = models.BooleanField(default=False)
    subiect_email = models.CharField(max_length=200, null=True, blank=True)  # noqa: DJ001
    email_trimis_la = models.DateTimeField(null=True, blank=True)
    incercari_email = models.SmallIntegerField(default=0)
    eroare_email = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "notificari"
        managed = False
        verbose_name = "notificare"
        verbose_name_plural = "notificări"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return self.mesaj

    @property
    def url_entitate(self) -> str | None:
        if not self.entitate_id:
            return None
        if self.entitate_tip == "document":
            return reverse("document_detaliu", kwargs={"document_id": self.entitate_id})
        if self.entitate_tip == "perioada":
            return reverse("perioada_detaliu", kwargs={"perioada_id": self.entitate_id})
        return None
