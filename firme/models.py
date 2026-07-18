import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Now


class FirmaContabilitate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    denumire = models.CharField(max_length=255)
    cui = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    activ = models.BooleanField(default=True)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "cabinete_contabilitate"
        managed = False
        verbose_name = "firmă de contabilitate"
        verbose_name_plural = "firme de contabilitate"
        ordering = ("denumire",)

    def __str__(self) -> str:
        return self.denumire


class Firma(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cabinet = models.ForeignKey(
        FirmaContabilitate,
        db_column="cabinet_id",
        on_delete=models.PROTECT,
        related_name="firme_cliente",
        verbose_name="firmă de contabilitate",
    )
    cui = models.CharField(max_length=20)
    denumire = models.CharField(max_length=255)
    adresa = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    email_contact = models.EmailField(max_length=255, null=True, blank=True)  # noqa: DJ001
    telefon_contact = models.CharField(max_length=30, null=True, blank=True)  # noqa: DJ001
    activa = models.BooleanField(default=True)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "firme"
        managed = False
        verbose_name = "firmă clientă"
        verbose_name_plural = "firme cliente"
        ordering = ("denumire",)
        unique_together = (("cabinet", "cui"),)

    def __str__(self) -> str:
        return f"{self.denumire} ({self.cui})"


class TipDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cod = models.CharField(max_length=50, unique=True)
    denumire = models.CharField(max_length=100)
    categorie = models.CharField(max_length=30)
    necesita_serie_numar = models.BooleanField(default=False)
    necesita_cont_financiar = models.BooleanField(default=False)
    tipuri_cont_compatibile = ArrayField(models.CharField(max_length=20), null=True, blank=True)
    retentie_ani = models.SmallIntegerField(null=True, blank=True)
    activ = models.BooleanField(default=True)

    class Meta:
        db_table = "tipuri_document"
        managed = False
        verbose_name = "tip de document"
        verbose_name_plural = "tipuri de document"
        ordering = ("denumire",)

    def __str__(self) -> str:
        return self.denumire


class ConfigurareDocumentFirma(models.Model):
    class Frecventa(models.TextChoices):
        LUNAR = "lunar", "Lunar"
        OCAZIONAL = "ocazional", "Ocazional"
        ZILNIC = "zilnic", "Zilnic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="configurari_documente",
    )
    tip_document = models.ForeignKey(
        TipDocument,
        db_column="tip_document_id",
        on_delete=models.PROTECT,
        related_name="configurari_firme",
    )
    obligatoriu = models.BooleanField(default=False)
    frecventa = models.CharField(max_length=20, choices=Frecventa.choices, default=Frecventa.LUNAR)
    termen_predare_zi = models.SmallIntegerField(null=True, blank=True)
    activ = models.BooleanField(default=True)
    observatii = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="configurari_documente_create",
    )
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "configurare_documente_firma"
        managed = False
        verbose_name = "configurare document"
        verbose_name_plural = "configurări documente"
        unique_together = (("firma", "tip_document"),)

    def __str__(self) -> str:
        return f"{self.firma_id}: {self.tip_document_id}"


class ContFinanciar(models.Model):
    class Tip(models.TextChoices):
        BANCA = "banca", "Cont bancar"
        CASA = "casa", "Casierie"
        CARD = "card", "Card"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="conturi_financiare",
    )
    tip = models.CharField(max_length=20, choices=Tip.choices)
    banca = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    iban = models.CharField(max_length=34, null=True, blank=True)  # noqa: DJ001
    moneda = models.CharField(max_length=3, default="RON")
    denumire = models.CharField(max_length=100)
    activ = models.BooleanField(default=True)

    class Meta:
        db_table = "conturi_financiare"
        managed = False
        verbose_name = "cont financiar"
        verbose_name_plural = "conturi financiare"
        ordering = ("denumire",)

    def __str__(self) -> str:
        return self.denumire


class Partener(models.Model):
    class Tip(models.TextChoices):
        FURNIZOR = "furnizor", "Furnizor"
        CLIENT = "client", "Client"
        AMBELE = "ambele", "Furnizor și client"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="parteneri",
    )
    tip = models.CharField(max_length=20, choices=Tip.choices)
    cui = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    denumire = models.CharField(max_length=255)
    tara = models.CharField(max_length=2, default="RO")
    activ = models.BooleanField(default=True)
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="parteneri_creati",
    )
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "parteneri"
        managed = False
        verbose_name = "partener"
        verbose_name_plural = "parteneri"
        ordering = ("denumire",)

    def __str__(self) -> str:
        return self.denumire
