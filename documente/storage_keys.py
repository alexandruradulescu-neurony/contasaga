from uuid import UUID


def prefix_lunar(*, firma_id: UUID | str, an: int, luna: int) -> str:
    if not 1 <= int(luna) <= 12:
        raise ValueError("Luna contabilă trebuie să fie între 1 și 12.")
    return f"clients/{firma_id}/{int(an):04d}-{int(luna):02d}"


def cheie_document(
    *,
    firma_id: UUID | str,
    an: int,
    luna: int,
    intentie_id: UUID | str,
) -> str:
    prefix = prefix_lunar(firma_id=firma_id, an=an, luna=luna)
    return f"{prefix}/documents/{intentie_id}"


def cheie_thumbnail(
    *,
    firma_id: UUID | str,
    an: int,
    luna: int,
    fisier_id: UUID | str,
) -> str:
    prefix = prefix_lunar(firma_id=firma_id, an=an, luna=luna)
    return f"{prefix}/thumbnails/{fisier_id}.png"


def cheie_temporara_inbox(
    *,
    firma_id: UUID | str,
    an: int,
    luna: int,
    lot_id: UUID | str,
    fisier_id: UUID | str,
) -> str:
    prefix = prefix_lunar(firma_id=firma_id, an=an, luna=luna)
    return f"{prefix}/_temp/{lot_id}/{fisier_id}.part"


def cheie_original_inbox(
    *,
    firma_id: UUID | str,
    an: int,
    luna: int,
    lot_id: UUID | str,
    fisier_id: UUID | str,
) -> str:
    prefix = prefix_lunar(firma_id=firma_id, an=an, luna=luna)
    return f"{prefix}/inbox/{lot_id}/originals/{fisier_id}"
