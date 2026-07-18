import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from firme.models import Firma
from perioade.models import PerioadaContabila


class Export(models.Model):
    class Status(models.TextChoices):
        IN_LUCRU = "in_lucru", "În lucru"
        FINALIZAT = "finalizat", "Finalizat"
        EROARE = "eroare", "Eroare"
        EXPIRAT = "expirat", "Expirat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="exporturi",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="exporturi",
    )
    solicitat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="solicitat_de",
        on_delete=models.PROTECT,
        related_name="exporturi_solicitate",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_LUCRU,
    )
    storage_key = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    eroare = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    expira_la = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "exporturi"
        managed = False
        verbose_name = "export"
        verbose_name_plural = "exporturi"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return f"{self.perioada_contabila_id}: {self.get_status_display()}"
