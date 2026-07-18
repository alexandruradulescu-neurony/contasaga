from pathlib import Path


class TipFisierInvalid(Exception):
    pass


TIPURI_DIN_EXTENSIE = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
}
TIPURI_PERMISE = frozenset(TIPURI_DIN_EXTENSIE.values())


def tip_pentru_upload(nume_fisier: str, tip_declarat: str | None) -> str:
    extensie = Path(nume_fisier).suffix.lower()
    tip_extensie = TIPURI_DIN_EXTENSIE.get(extensie)
    if tip_extensie is None:
        raise TipFisierInvalid("Sunt permise doar fișiere PDF, JPG, PNG, HEIC sau HEIF.")
    tip_declarat = (tip_declarat or "").lower().split(";", maxsplit=1)[0].strip()
    if tip_declarat in {"", "application/octet-stream"}:
        return tip_extensie
    echivalente = {tip_extensie}
    if tip_extensie == "image/heic":
        echivalente.add("image/heif")
    if tip_extensie == "image/heif":
        echivalente.add("image/heic")
    if tip_declarat not in echivalente:
        raise TipFisierInvalid("Extensia fișierului nu corespunde tipului declarat.")
    return tip_extensie


def detecteaza_tip(continut: bytes) -> str:
    if continut.startswith(b"%PDF-"):
        return "application/pdf"
    if continut.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if continut.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(continut) >= 12 and continut[4:8] == b"ftyp":
        marci = continut[8:32]
        if any(marca in marci for marca in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")):
            return "image/heic"
    raise TipFisierInvalid("Conținutul fișierului nu corespunde unui format permis.")


def tipuri_compatibile(asteptat: str, detectat: str) -> bool:
    if asteptat == detectat:
        return True
    return {asteptat, detectat} <= {"image/heic", "image/heif"}
