import uuid

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone

from firme.models import Firma, FirmaContabilitate

from .managers import UtilizatorManager


class Utilizator(AbstractBaseUser):
    class Rol(models.TextChoices):
        SUPERUSER_PLATFORMA = "superuser_platforma", "Superuser platformă"
        ADMIN_CABINET = "admin_cabinet", "Administrator firmă de contabilitate"
        CONTABIL_COORDONATOR = "contabil_coordonator", "Contabil coordonator"
        CONTABIL = "contabil", "Contabil"
        CLIENT_ADMIN = "client_admin", "Administrator client"
        CLIENT_OPERATOR = "client_operator", "Operator client"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cabinet_id = models.UUIDField(null=True, blank=True)
    nume = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True)
    password = models.CharField(max_length=255, db_column="parola_hash")
    rol = models.CharField(max_length=30, choices=Rol.choices)
    telefon = models.CharField(max_length=30, null=True, blank=True)  # noqa: DJ001
    is_active = models.BooleanField(db_column="activ", default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    objects = UtilizatorManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["nume"]

    class Meta:
        db_table = "utilizatori"
        managed = False
        verbose_name = "utilizator"
        verbose_name_plural = "utilizatori"

    def __str__(self) -> str:
        return f"{self.nume} <{self.email}>"

    def get_full_name(self) -> str:
        return self.nume

    def get_short_name(self) -> str:
        return self.nume.split(maxsplit=1)[0]

    def has_perm(self, perm: str, obj=None) -> bool:
        return bool(self.is_active and self.is_superuser)

    def has_module_perms(self, app_label: str) -> bool:
        return bool(self.is_active and self.is_superuser)


class UtilizatorFirma(models.Model):
    class Rol(models.TextChoices):
        CONTABIL_ALOCAT = "contabil_alocat", "Contabil alocat"
        REPREZENTANT_CLIENT = "reprezentant_client", "Reprezentant client"
        OPERATOR_UPLOAD = "operator_upload", "Operator încărcare"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilizator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="utilizator_id",
        on_delete=models.PROTECT,
        related_name="alocari_firme",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        related_name="alocari_utilizatori",
    )
    rol_in_firma = models.CharField(max_length=30, choices=Rol.choices)
    data_alocare = models.DateTimeField(db_default=Now(), editable=False)
    alocat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="alocat_de",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="alocari_create",
    )

    class Meta:
        db_table = "utilizator_firma"
        managed = False
        verbose_name = "alocare la firmă"
        verbose_name_plural = "alocări la firme"
        unique_together = (("utilizator", "firma"),)

    def __str__(self) -> str:
        return f"{self.utilizator_id} → {self.firma_id}"


class Invitatie(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cabinet = models.ForeignKey(
        FirmaContabilitate,
        db_column="cabinet_id",
        verbose_name="firmă de contabilitate",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invitatii_interne",
    )
    firma = models.ForeignKey(
        Firma,
        db_column="firma_id",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invitatii_clienti",
    )
    email = models.EmailField(max_length=255)
    rol = models.CharField(max_length=30, choices=Utilizator.Rol.choices)
    rol_in_firma = models.CharField(  # noqa: DJ001
        max_length=30,
        choices=UtilizatorFirma.Rol.choices,
        null=True,
        blank=True,
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expira_la = models.DateTimeField()
    acceptata_la = models.DateTimeField(null=True, blank=True)
    anulata_la = models.DateTimeField(null=True, blank=True)
    creat_de = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="creat_de",
        on_delete=models.PROTECT,
        related_name="invitatii_create",
    )
    creat_la = models.DateTimeField(db_default=Now(), editable=False)

    class Meta:
        db_table = "invitatii"
        managed = False
        verbose_name = "invitație"
        verbose_name_plural = "invitații"
        ordering = ("-creat_la",)

    def __str__(self) -> str:
        return f"{self.email} — {self.get_rol_display()}"

    @property
    def status(self) -> str:
        if self.acceptata_la:
            return "Acceptată"
        if self.anulata_la:
            return "Anulată"
        if self.expira_la <= timezone.now():
            return "Expirată"
        return "În așteptare"

    @property
    def poate_fi_anulata(self) -> bool:
        return not self.acceptata_la and not self.anulata_la and self.expira_la > timezone.now()
