import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from firme.models import Firma
from perioade.models import PerioadaContabila


class PredareDocumente(models.Model):
    class Metoda(models.TextChoices):
        CURIER = "curier", "Curier"
        POSTA = "posta", "Poștă"
        RIDICARE_CONTABIL = "ridicare_contabil", "Ridicare de către contabil"
        PREDARE_CLIENT = "predare_client", "Predare de către client"
        EXCLUSIV_DIGITAL = "exclusiv_digital", "Exclusiv digital"

    class Status(models.TextChoices):
        PROGRAMATA = "programata", "Programată"
        PRELUATA = "preluata", "Preluată"
        RECEPTIONATA = "receptionata", "Recepționată"
        RETURNATA = "returnata", "Returnată"

    class StatusDigitizare(models.TextChoices):
        NEDECISA = "nedecisa", "Nedecisă"
        NU_E_NECESARA = "nu_este_necesara", "Nu este necesară"
        IN_LUCRU = "in_lucru", "În lucru"
        FINALIZATA = "finalizata", "Finalizată"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="predari_documente",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="predari_documente",
    )
    metoda = models.CharField(max_length=30, choices=Metoda.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROGRAMATA,
    )
    predat_de = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    preluat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="preluat_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="predari_preluate",
    )
    numar_cutii = models.IntegerField(default=0)
    data_programata = models.DateTimeField(null=True, blank=True)
    data_preluare = models.DateTimeField(null=True, blank=True)
    data_receptie = models.DateTimeField(null=True, blank=True)
    data_returnare = models.DateTimeField(null=True, blank=True)
    digitizare_status = models.CharField(
        max_length=30,
        choices=StatusDigitizare.choices,
        default=StatusDigitizare.NEDECISA,
    )
    numar_documente_estimat = models.IntegerField(null=True, blank=True)
    digitizare_inceputa_la = models.DateTimeField(null=True, blank=True)
    digitizare_inceputa_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="digitizare_inceputa_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="digitizari_incepute",
    )
    digitizare_finalizata_la = models.DateTimeField(null=True, blank=True)
    digitizare_finalizata_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="digitizare_finalizata_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="digitizari_finalizate",
    )
    observatii = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="predari_create",
    )
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "predari_documente"
        managed = False
        verbose_name = "predare de documente"
        verbose_name_plural = "predări de documente"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return f"{self.firma_id}: {self.get_metoda_display()} — {self.get_status_display()}"
