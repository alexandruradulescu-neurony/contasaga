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


class LotIncarcare(models.Model):
    class Status(models.TextChoices):
        IN_DESFASURARE = "in_desfasurare", "În desfășurare"
        FINALIZAT = "finalizat", "Finalizat"
        PARTIAL = "partial", "Finalizat parțial"
        ANULAT = "anulat", "Anulat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="loturi_incarcare",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="loturi_incarcare",
    )
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        related_name="loturi_incarcare_create",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_DESFASURARE,
    )
    numar_fisiere_declarat = models.PositiveIntegerField()
    dimensiune_totala_declarata = models.BigIntegerField()
    nota = models.TextField(null=True, blank=True)  # noqa: DJ001
    finalizat_la = models.DateTimeField(null=True, blank=True)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "loturi_incarcare"
        managed = False
        verbose_name = "lot de încărcare"
        verbose_name_plural = "loturi de încărcare"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return f"{self.perioada_contabila_id} · {self.pk}"


class FisierInbox(models.Model):
    class Status(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "În așteptarea încărcării"
        DISPONIBIL = "disponibil", "Disponibil pentru clasificare"
        EROARE = "eroare", "Eroare"
        EXPIRAT = "expirat", "Expirat"
        CLASIFICAT = "clasificat", "Clasificat"
        IGNORAT = "ignorat", "Ignorat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lot = models.ForeignKey(
        LotIncarcare,
        db_column="lot_id",
        on_delete=models.PROTECT,
        related_name="fisiere",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="fisiere_inbox",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="fisiere_inbox",
    )
    incarcat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="incarcat_de",
        on_delete=models.PROTECT,
        related_name="fisiere_inbox_incarcate",
    )
    temp_storage_key = models.CharField(max_length=500)
    storage_key = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    nume_original = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    dimensiune_declarata = models.BigIntegerField()
    dimensiune_bytes = models.BigIntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_ASTEPTARE,
    )
    eroare = models.TextField(null=True, blank=True)  # noqa: DJ001
    expira_la = models.DateTimeField(db_default=Now())
    incarcat_la = models.DateTimeField(null=True, blank=True)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "fisiere_inbox"
        managed = False
        verbose_name = "fișier inbox"
        verbose_name_plural = "fișiere inbox"
        ordering = ("creat_la",)

    def __str__(self) -> str:
        return self.nume_original


class AnalizaFisierInbox(models.Model):
    class Status(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "În așteptare"
        IN_LUCRU = "in_lucru", "În analiză"
        FINALIZATA = "finalizata", "Analizată"
        EROARE = "eroare", "Eroare"

    class StatusRevizuire(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "Așteaptă contabilul"
        CONFIRMATA = "confirmata", "Sugestie confirmată"
        CORECTATA = "corectata", "Sugestie corectată"
        SEGMENTATA = "segmentata", "Separare confirmată"
        IGNORATA = "ignorata", "Fișier ignorat"

    class StatusCitire(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "Așteaptă citirea"
        IN_LUCRU = "in_lucru", "În citire"
        FINALIZATA = "finalizata", "Citit"
        EROARE = "eroare", "Eroare de citire"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fisier_inbox = models.OneToOneField(
        FisierInbox,
        db_column="fisier_inbox_id",
        on_delete=models.PROTECT,
        related_name="analiza",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="analize_fisiere_inbox",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="analize_fisiere_inbox",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_ASTEPTARE,
    )
    provider = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    model = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    versiune_prompt = models.CharField(max_length=50, default="document-classifier-v1")
    incercari = models.SmallIntegerField(default=0)
    procesare_inceputa_la = models.DateTimeField(null=True, blank=True)
    reincearca_dupa = models.DateTimeField(db_default=Now())
    finalizata_la = models.DateTimeField(null=True, blank=True)
    eroare = models.TextField(null=True, blank=True)  # noqa: DJ001
    tip_document_sugerat = models.ForeignKey(
        TipDocument,
        db_column="tip_document_sugerat_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analize_sugerate",
    )
    cont_financiar_sugerat = models.ForeignKey(
        ContFinanciar,
        db_column="cont_financiar_sugerat_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analize_sugerate",
    )
    directie_sugerata = models.CharField(  # noqa: DJ001
        max_length=10,
        choices=Document.Directie.choices,
        null=True,
        blank=True,
    )
    incredere = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    rezumat = models.TextField(null=True, blank=True)  # noqa: DJ001
    text_extras = models.TextField(null=True, blank=True)  # noqa: DJ001
    dovezi = models.JSONField(default=list)
    raspuns_provider_id = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    tokeni_intrare = models.PositiveIntegerField(null=True, blank=True)
    tokeni_iesire = models.PositiveIntegerField(null=True, blank=True)
    status_citire = models.CharField(
        max_length=20,
        choices=StatusCitire.choices,
        default=StatusCitire.IN_ASTEPTARE,
    )
    incercari_citire = models.SmallIntegerField(default=0)
    citire_inceputa_la = models.DateTimeField(null=True, blank=True)
    reincearca_citire_dupa = models.DateTimeField(db_default=Now())
    citire_finalizata_la = models.DateTimeField(null=True, blank=True)
    eroare_citire = models.TextField(null=True, blank=True)  # noqa: DJ001
    metoda_citire = models.CharField(max_length=20, null=True, blank=True)  # noqa: DJ001
    numar_pagini = models.SmallIntegerField(null=True, blank=True)
    limite_sugerate = models.JSONField(default=list)
    campuri_extrase = models.JSONField(default=dict)
    avertismente_extragere = models.JSONField(default=list)
    status_revizuire = models.CharField(
        max_length=20,
        choices=StatusRevizuire.choices,
        default=StatusRevizuire.IN_ASTEPTARE,
    )
    revizuita_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="revizuita_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analize_fisiere_revizuite",
    )
    revizuita_la = models.DateTimeField(null=True, blank=True)
    tip_document_final = models.ForeignKey(
        TipDocument,
        db_column="tip_document_final_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analize_confirmate",
    )
    cont_financiar_final = models.ForeignKey(
        ContFinanciar,
        db_column="cont_financiar_final_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analize_confirmate",
    )
    directie_finala = models.CharField(  # noqa: DJ001
        max_length=10,
        choices=Document.Directie.choices,
        null=True,
        blank=True,
    )
    document = models.OneToOneField(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="analiza_sursa_inbox",
    )
    observatii_revizuire = models.TextField(null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "analize_fisiere_inbox"
        managed = False
        verbose_name = "analiză fișier inbox"
        verbose_name_plural = "analize fișiere inbox"
        ordering = ("creat_la",)

    def __str__(self) -> str:
        return f"{self.fisier_inbox_id} · {self.get_status_display()}"


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


class PaginaFisierInbox(models.Model):
    class Metoda(models.TextChoices):
        TEXT_PDF = "text_pdf", "Text PDF"
        TESSERACT = "tesseract", "OCR Tesseract"
        FARA_TEXT = "fara_text", "Fără text detectat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analiza = models.ForeignKey(
        AnalizaFisierInbox,
        db_column="analiza_id",
        on_delete=models.PROTECT,
        related_name="pagini",
    )
    fisier_inbox = models.ForeignKey(
        FisierInbox,
        db_column="fisier_inbox_id",
        on_delete=models.PROTECT,
        related_name="pagini_extrase",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="pagini_fisiere_inbox",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="pagini_fisiere_inbox",
    )
    numar_pagina = models.SmallIntegerField()
    metoda = models.CharField(max_length=20, choices=Metoda.choices)
    text_extras = models.TextField(blank=True, default="")
    incredere_ocr = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    preview_storage_key = models.CharField(max_length=500, unique=True)
    preview_checksum = models.CharField(max_length=64)
    latime_preview = models.PositiveIntegerField()
    inaltime_preview = models.PositiveIntegerField()
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "pagini_fisiere_inbox"
        managed = False
        verbose_name = "pagină fișier inbox"
        verbose_name_plural = "pagini fișiere inbox"
        ordering = ("numar_pagina",)

    def __str__(self) -> str:
        return f"{self.fisier_inbox_id} · pagina {self.numar_pagina}"


class DerivareFisierInbox(models.Model):
    class Metoda(models.TextChoices):
        COPIE_INTEGRALA = "copie_integrala", "Copie integrală"
        EXTRAGERE_PAGINI = "extragere_pagini", "Extragere pagini"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    analiza = models.ForeignKey(
        AnalizaFisierInbox,
        db_column="analiza_id",
        on_delete=models.PROTECT,
        related_name="derivari",
    )
    fisier_inbox = models.ForeignKey(
        FisierInbox,
        db_column="fisier_inbox_id",
        on_delete=models.PROTECT,
        related_name="derivari",
    )
    fisier_document = models.ForeignKey(
        FisierDocument,
        db_column="fisier_document_id",
        on_delete=models.PROTECT,
        related_name="derivare_inbox",
    )
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        related_name="derivari_inbox",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="derivari_fisiere_inbox",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="derivari_fisiere_inbox",
    )
    pagina_start = models.SmallIntegerField()
    pagina_sfarsit = models.SmallIntegerField()
    metoda = models.CharField(max_length=30, choices=Metoda.choices)
    checksum_sursa = models.CharField(max_length=64)
    checksum_derivat = models.CharField(max_length=64)
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        related_name="derivari_fisiere_inbox_create",
    )
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "derivari_fisiere_inbox"
        managed = False
        verbose_name = "derivare fișier inbox"
        verbose_name_plural = "derivări fișiere inbox"
        ordering = ("pagina_start",)

    def __str__(self) -> str:
        return f"{self.fisier_inbox_id} · {self.pagina_start}-{self.pagina_sfarsit}"


class ExtractieStructurataDocument(models.Model):
    class Status(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "În așteptare"
        IN_LUCRU = "in_lucru", "În extragere"
        FINALIZATA = "finalizata", "Extrasă"
        EROARE = "eroare", "Eroare"

    class StatusRevizuire(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "Așteaptă contabilul"
        CONFIRMATA = "confirmata", "Confirmată"
        CORECTATA = "corectata", "Corectată"
        MANUALA = "manuala", "Completare manuală"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        related_name="extractii_structurate",
    )
    fisier_document = models.ForeignKey(
        FisierDocument,
        db_column="fisier_document_id",
        on_delete=models.PROTECT,
        related_name="extractii_structurate",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="extractii_structurate",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="extractii_structurate",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_ASTEPTARE)
    provider = models.CharField(max_length=50, null=True, blank=True)  # noqa: DJ001
    model = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    versiune_prompt = models.CharField(max_length=50, default="structured-extraction-v1")
    incercari = models.SmallIntegerField(default=0)
    procesare_inceputa_la = models.DateTimeField(null=True, blank=True)
    reincearca_dupa = models.DateTimeField(db_default=Now())
    finalizata_la = models.DateTimeField(null=True, blank=True)
    eroare = models.TextField(null=True, blank=True)  # noqa: DJ001
    checksum_sursa = models.CharField(max_length=64)
    fisiere_sursa = models.JSONField(default=list)
    campuri_sugerate = models.JSONField(default=dict)
    avertismente = models.JSONField(default=list)
    incredere = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    raspuns_provider_id = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    tokeni_intrare = models.PositiveIntegerField(null=True, blank=True)
    tokeni_iesire = models.PositiveIntegerField(null=True, blank=True)
    status_revizuire = models.CharField(
        max_length=20,
        choices=StatusRevizuire.choices,
        default=StatusRevizuire.IN_ASTEPTARE,
    )
    revizuita_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="revizuita_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="extractii_structurate_revizuite",
    )
    revizuita_la = models.DateTimeField(null=True, blank=True)
    campuri_finale = models.JSONField(default=dict)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "extractii_structurate_documente"
        managed = False
        verbose_name = "extragere structurată"
        verbose_name_plural = "extrageri structurate"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return f"{self.document_id} · {self.get_status_display()}"


class ArhivaLunara(models.Model):
    class Status(models.TextChoices):
        IN_ASTEPTARE = "in_asteptare", "În așteptare"
        IN_LUCRU = "in_lucru", "În pregătire"
        FINALIZATA = "finalizata", "Finalizată"
        EROARE = "eroare", "Eroare"
        INLOCUITA = "inlocuita", "Înlocuită de o versiune nouă"
        ANULATA = "anulata", "Anulată"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="arhive_lunare",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="arhive_lunare",
    )
    versiune = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_ASTEPTARE)
    prefix_staging = models.CharField(max_length=500)
    prefix_final = models.CharField(max_length=500)
    manifest_storage_key = models.CharField(max_length=500, null=True, blank=True)  # noqa: DJ001
    manifest_checksum = models.CharField(max_length=64, null=True, blank=True)  # noqa: DJ001
    numar_fisiere = models.PositiveIntegerField(default=0)
    dimensiune_totala = models.BigIntegerField(default=0)
    incercari = models.SmallIntegerField(default=0)
    procesare_inceputa_la = models.DateTimeField(null=True, blank=True)
    reincearca_dupa = models.DateTimeField(db_default=Now())
    finalizata_la = models.DateTimeField(null=True, blank=True)
    eroare = models.TextField(null=True, blank=True)  # noqa: DJ001
    solicitata_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="solicitata_de",
        on_delete=models.PROTECT,
        related_name="arhive_lunare_solicitate",
    )
    audit_ip = models.GenericIPAddressField(null=True, blank=True)
    audit_user_agent = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    creat_la = models.DateTimeField(db_default=Now(), editable=False)
    actualizat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "arhive_lunare"
        managed = False
        verbose_name = "arhivă lunară"
        verbose_name_plural = "arhive lunare"
        ordering = ("-versiune",)

    def __str__(self) -> str:
        return f"{self.perioada_contabila_id} · v{self.versiune}"


class FisierArhivaLunara(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    arhiva = models.ForeignKey(
        ArhivaLunara,
        db_column="arhiva_id",
        on_delete=models.PROTECT,
        related_name="fisiere",
    )
    document = models.ForeignKey(
        Document,
        db_column="document_id",
        on_delete=models.PROTECT,
        related_name="fisiere_arhivate",
    )
    fisier_document = models.ForeignKey(
        FisierDocument,
        db_column="fisier_document_id",
        on_delete=models.PROTECT,
        related_name="copii_arhiva",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="fisiere_arhiva_lunara",
    )
    perioada_contabila = models.ForeignKey(
        PerioadaContabila,
        db_column="perioada_contabila_id",
        on_delete=models.PROTECT,
        related_name="fisiere_arhiva_lunara",
    )
    ordine = models.PositiveIntegerField()
    categorie = models.CharField(max_length=150)
    cale_relativa = models.CharField(max_length=500)
    storage_key_sursa = models.CharField(max_length=500)
    storage_key_arhiva = models.CharField(max_length=500, unique=True)
    nume_original = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    checksum_sursa = models.CharField(max_length=64)
    checksum_arhiva = models.CharField(max_length=64)
    dimensiune_bytes = models.BigIntegerField()
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "fisiere_arhiva_lunara"
        managed = False
        verbose_name = "fișier arhivă lunară"
        verbose_name_plural = "fișiere arhivă lunară"
        ordering = ("ordine",)

    def __str__(self) -> str:
        return self.cale_relativa


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
