import uuid

from django.db import models
from django.db.models.functions import Now


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma_id = models.UUIDField(null=True, blank=True)
    utilizator_id = models.UUIDField(null=True, blank=True)
    entitate_tip = models.CharField(max_length=30)
    entitate_id = models.UUIDField(null=True, blank=True)
    actiune = models.CharField(max_length=40)
    date_vechi = models.JSONField(null=True, blank=True)
    date_noi = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "audit_log"
        managed = False
        verbose_name = "eveniment de audit"
        verbose_name_plural = "evenimente de audit"

    def __str__(self) -> str:
        return f"{self.entitate_tip}:{self.actiune}"


class IstoricStare(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma_id = models.UUIDField()
    entitate_tip = models.CharField(max_length=30)
    entitate_id = models.UUIDField()
    stare_veche = models.CharField(max_length=30, null=True, blank=True)  # noqa: DJ001
    stare_noua = models.CharField(max_length=30)
    utilizator_id = models.UUIDField()
    comentariu = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "istoric_stari"
        managed = False
        verbose_name = "schimbare de stare"
        verbose_name_plural = "istoric stări"
        ordering = ("creat_la",)

    def __str__(self) -> str:
        return f"{self.entitate_tip}: {self.stare_veche} → {self.stare_noua}"
