import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Now

from firme.models import ContFinanciar, Firma, Partener, TipDocument
from logistica.models import PredareDocumente
from perioade.models import PerioadaContabila


class Document(models.Model):
    class Stare(models.TextChoices):
        DRAFT = "draft", "Ciornă"
        TRIMIS = "trimis", "Trimis"
        IN_VERIFICARE = "in_verificare", "În verificare"
        NECESITA_CLARIFICARI = "necesita_clarificari", "Necesită clarificări"
        ACCEPTAT = "acceptat", "Acceptat"
        PROCESAT = "procesat", "Procesat"
        ARHIVAT = "arhivat", "Arhivat"
        ANULAT = "anulat", "Anulat"

    class Directie(models.TextChoices):
        PRIMIT = "primit", "Primit"
        EMIS = "emis", "Emis"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="documente",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="documente",
    )
    tip_document = models.ForeignKey(
        TipDocument,
        db_column="tip_document_id",
        on_delete=models.PROTECT,
        related_name="documente",
    )
    partener = models.ForeignKey(
        Partener,
        db_column="partener_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documente",
    )
    cont_financiar = models.ForeignKey(
        ContFinanciar,
        db_column="cont_financiar_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documente",
    )
    predare_documente = models.ForeignKey(
        PredareDocumente,
        db_column="predare_documente_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documente_digitizate",
    )
    incarcat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="incarcat_de",
        on_delete=models.PROTECT,
        related_name="documente_incarcate",
    )
    directie = models.CharField(max_length=10, choices=Directie.choices, null=True, blank=True)  # noqa: DJ001
    serie = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    numar = models.CharField(max_length=30, null=True, blank=True)  # noqa: DJ001
    data_document = models.DateField(null=True, blank=True)
    data_scadenta = models.DateField(null=True, blank=True)
    moneda = models.CharField(max_length=3, default="RON")
    valoare_fara_tva = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    valoare_tva = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    valoare_totala = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    stare = models.CharField(max_length=30, choices=Stare.choices, default=Stare.DRAFT)
    incarcat_dupa_confirmare = models.BooleanField(default=False)
    retentie_extinsa_pana_la = models.DateField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)  # noqa: DJ001
    sters_la = models.DateTimeField(null=True, blank=True)
    sters_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="sters_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documente_sterse",
    )
    motiv_stergere = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "documente"
        managed = False
        verbose_name = "document"
        verbose_name_plural = "documente"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        identificator = " ".join(filter(None, (self.serie, self.numar)))
        return identificator or f"{self.tip_document_id} · {self.pk}"


class IntentieUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="intentii_upload",
    )
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        related_name="intentii_upload",
    )
    inlocuieste_fisier = models.ForeignKey(
        "FisierDocument",
        db_column="inlocuieste_fisier_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="intentii_inlocuire",
    )
    utilizator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="utilizator_id",
        on_delete=models.PROTECT,
        related_name="intentii_upload",
    )
    storage_key = models.CharField(max_length=500, db_default="")
    nume_original = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    expira_la = models.DateTimeField(db_default=Now())
    folosita_la = models.DateTimeField(null=True, blank=True)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "intentii_upload"
        managed = False
        verbose_name = "intenție de încărcare"
        verbose_name_plural = "intenții de încărcare"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return self.nume_original or str(self.pk)


class FisierDocument(models.Model):
    class StareProcesare(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "În așteptare"
        IN_LUCRU = "in_lucru", "În lucru"
        PROCESAT = "procesat", "Procesat"
        EROARE = "eroare", "Eroare"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        related_name="fisiere",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="fisiere_documente",
    )
    upload_intentie = models.OneToOneField(
        IntentieUpload,
        db_column="upload_intentie_id",
        on_delete=models.PROTECT,
        related_name="fisier",
    )
    storage_key = models.CharField(max_length=500)
    nume_original = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    mime_type = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    dimensiune_bytes = models.BigIntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    numar_pagini = models.IntegerField(null=True, blank=True)
    ordine = models.SmallIntegerField(default=1)
    versiune = models.IntegerField(default=1)
    inlocuieste_fisier = models.ForeignKey(
        "self",
        db_column="inlocuieste_fisier_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="versiuni_ulterioare",
    )
    stare_procesare = models.CharField(
        max_length=20,
        choices=StareProcesare.choices,
        default=StareProcesare.IN_ASTEPTARE,
    )
    procesare_inceputa_la = models.DateTimeField(null=True, blank=True)
    eroare_procesare = models.TextField(null=True, blank=True)  # noqa: DJ001
    incercari_procesare = models.SmallIntegerField(default=0)
    thumbnail_key = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    incarcat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="incarcat_de",
        on_delete=models.PROTECT,
        related_name="fisiere_incarcate",
    )
    incarcat_la = models.DateTimeField(db_default=Now(), editable=False)
    activ = models.BooleanField(default=True)
    sters_la = models.DateTimeField(null=True, blank=True)
    sters_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="sters_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fisiere_sterse",
    )

    class Meta:
        db_table = "fisiere_document"
        managed = False
        verbose_name = "fișier document"
        verbose_name_plural = "fișiere document"
        ordering = ("ordine", "versiune")

    def __str__(self) -> str:
        return self.nume_original or self.storage_key


class Comentariu(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="comentarii",
    )
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comentarii",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comentarii",
    )
    utilizator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="utilizator_id",
        on_delete=models.PROTECT,
        related_name="comentarii",
    )
    text = models.TextField()
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "comentarii"
        managed = False
        verbose_name = "comentariu"
        verbose_name_plural = "comentarii"
        ordering = ("creat_la",)

    def __str__(self) -> str:
        return self.text[:80]
