from dataclasses import dataclass
from hashlib import sha256

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from documente.models import FisierDocument, IntentieUpload
from documente.storage import EroareStorage, get_document_storage
from documente.storage_keys import cheie_document, cheie_thumbnail


@dataclass(frozen=True)
class MutareObiect:
    veche: str
    noua: str
    content_type: str
    lipsa_permisa: bool


class Command(BaseCommand):
    help = "Mută obiectele legacy în directoare client/lună și actualizează referințele."

    def _copiaza(self, mutare: MutareObiect) -> bool:
        storage = get_document_storage()
        try:
            metadata_sursa = storage.head(mutare.veche)
        except EroareStorage as exc_sursa:
            try:
                storage.head(mutare.noua)
                return False
            except EroareStorage:
                if mutare.lipsa_permisa:
                    return False
                raise CommandError(
                    f"Obiectul activ lipsește din storage: {mutare.veche}"
                ) from exc_sursa

        continut_sursa = storage.read_bytes(mutare.veche)
        try:
            storage.head(mutare.noua)
            continut_tinta = storage.read_bytes(mutare.noua)
        except EroareStorage:
            storage.put_bytes(
                mutare.noua,
                continut_sursa,
                metadata_sursa.content_type or mutare.content_type,
            )
            continut_tinta = storage.read_bytes(mutare.noua)

        if (
            len(continut_tinta) != metadata_sursa.dimensiune
            or sha256(continut_tinta).digest() != sha256(continut_sursa).digest()
        ):
            raise CommandError(f"Obiectul țintă diferă de sursă: {mutare.noua}")
        return True

    def handle(self, *args, **options):
        fisiere = {
            fisier.upload_intentie_id: fisier
            for fisier in FisierDocument.objects.using("privileged")
            .select_related("document__perioada_contabila")
            .all()
        }
        intentii = list(
            IntentieUpload.objects.using("privileged")
            .select_related("document__perioada_contabila")
            .all()
        )

        chei_intentii: dict[object, str] = {}
        chei_thumbnail: dict[object, str] = {}
        mutari: list[MutareObiect] = []

        for intentie in intentii:
            perioada = intentie.document.perioada_contabila
            cheie_noua = cheie_document(
                firma_id=intentie.firma_id,
                an=perioada.an,
                luna=perioada.luna,
                intentie_id=intentie.pk,
            )
            if intentie.storage_key == cheie_noua:
                continue
            fisier = fisiere.get(intentie.pk)
            chei_intentii[intentie.pk] = cheie_noua
            mutari.append(
                MutareObiect(
                    veche=intentie.storage_key,
                    noua=cheie_noua,
                    content_type=(
                        fisier.mime_type
                        if fisier and fisier.mime_type
                        else "application/octet-stream"
                    ),
                    lipsa_permisa=fisier is None or fisier.sters_la is not None,
                )
            )

        for fisier in fisiere.values():
            if not fisier.thumbnail_key:
                continue
            perioada = fisier.document.perioada_contabila
            cheie_noua = cheie_thumbnail(
                firma_id=fisier.firma_id,
                an=perioada.an,
                luna=perioada.luna,
                fisier_id=fisier.pk,
            )
            if fisier.thumbnail_key == cheie_noua:
                continue
            chei_thumbnail[fisier.pk] = cheie_noua
            mutari.append(
                MutareObiect(
                    veche=fisier.thumbnail_key,
                    noua=cheie_noua,
                    content_type="image/png",
                    lipsa_permisa=fisier.sters_la is not None,
                )
            )

        surse_de_sters = [mutare.veche for mutare in mutari if self._copiaza(mutare)]

        with transaction.atomic(using="privileged"):
            with connections["privileged"].cursor() as cursor:
                cursor.execute("SET CONSTRAINTS fk_fisier_upload_intentie DEFERRED")
            for intentie_id, cheie_noua in chei_intentii.items():
                IntentieUpload.objects.using("privileged").filter(pk=intentie_id).update(
                    storage_key=cheie_noua
                )
                FisierDocument.objects.using("privileged").filter(
                    upload_intentie_id=intentie_id
                ).update(storage_key=cheie_noua)
            for fisier_id, cheie_noua in chei_thumbnail.items():
                FisierDocument.objects.using("privileged").filter(pk=fisier_id).update(
                    thumbnail_key=cheie_noua
                )

        storage = get_document_storage()
        for cheie_veche in surse_de_sters:
            try:
                storage.delete(cheie_veche)
            except Exception as exc:  # obiectul nou și referința DB sunt deja valide
                self.stderr.write(
                    self.style.WARNING(f"Nu am șters duplicatul {cheie_veche}: {exc}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Layout storage migrat: "
                f"{len(chei_intentii)} obiecte document, "
                f"{len(chei_thumbnail)} thumbnails."
            )
        )
