import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from firme.models import ContFinanciar, Firma, TipDocument


class PerioadaContabila(models.Model):
    class Stare(models.TextChoices):
        DESCHISA = "deschisa", "Deschisă"
        DOCUMENTE_INCOMPLETE = "documente_incomplete", "Documente incomplete"
        GATA_PENTRU_VERIFICARE = "gata_pentru_verificare", "Gata pentru verificare"
        IN_LUCRU = "in_lucru", "În lucru"
        INCHIDERE_IN_CURS = "inchidere_in_curs", "În curs de închidere"
        INCHISA = "inchisa", "Închisă"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="perioade_contabile",
    )
    luna = models.SmallIntegerField()
    an = models.SmallIntegerField()
    stare = models.CharField(max_length=30, choices=Stare.choices, default=Stare.DESCHISA)
    termen_predare = models.DateField(null=True, blank=True)
    contabil_responsabil = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="contabil_responsabil_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="perioade_responsabil",
    )
    confirmata_de_client_la = models.DateTimeField(null=True, blank=True)
    inchisa_la = models.DateTimeField(null=True, blank=True)
    inchisa_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="inchisa_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="perioade_inchise",
    )
    observatii = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "perioade_contabile"
        managed = False
        verbose_name = "perioadă contabilă"
        verbose_name_plural = "perioade contabile"
        ordering = ("-an", "-luna")
        unique_together = (("firma", "luna", "an"),)

    def __str__(self) -> str:
        return f"{self.firma_id}: {self.luna:02d}/{self.an}"


class CerintaDocumentPerioada(models.Model):
    class Status(models.TextChoices):
        LIPSA = "lipsa", "Lipsă"
        PARTIAL = "partial", "Parțial"
        PRIMIT = "primit", "Primit"
        NU_SE_APLICA = "nu_se_aplica", "Nu se aplică"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="cerinte",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="cerinte_documente",
    )
    tip_document = models.ForeignKey(
        TipDocument,
        db_column="tip_document_id",
        on_delete=models.PROTECT,
        related_name="cerinte_perioade",
    )
    cont_financiar = models.ForeignKey(
        ContFinanciar,
        db_column="cont_financiar_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cerinte_perioade",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.LIPSA)
    numar_documente_declarat = models.IntegerField(null=True, blank=True)
    observatii_client = models.TextField(null=True, blank=True)  # noqa: DJ001
    observatii_contabil = models.TextField(null=True, blank=True)  # noqa: DJ001
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "cerinte_documente_perioada"
        managed = False
        verbose_name = "cerință document"
        verbose_name_plural = "cerințe documente"
        ordering = ("tip_document__denumire",)

    def __str__(self) -> str:
        return f"{self.tip_document_id}: {self.status}"
