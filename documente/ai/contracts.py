from dataclasses import dataclass, field
from typing import Protocol


class EroareAnalizaAI(Exception):
    """Eroare sigură pentru retry, fără expunerea secretelor providerului."""


@dataclass(frozen=True)
class TipDocumentPermis:
    id: str
    cod: str
    denumire: str
    necesita_cont_financiar: bool


@dataclass(frozen=True)
class ContFinanciarPermis:
    id: str
    denumire: str
    tip: str
    moneda: str


@dataclass(frozen=True)
class PaginaTextAnaliza:
    numar: int
    text: str


@dataclass(frozen=True)
class ContextAnalizaDocument:
    nume_fisier: str
    mime_type: str
    continut: bytes
    denumire_firma: str
    cui_firma: str
    tipuri_document: tuple[TipDocumentPermis, ...]
    conturi_financiare: tuple[ContFinanciarPermis, ...]
    pagini_text: tuple[PaginaTextAnaliza, ...] = ()


@dataclass(frozen=True)
class AnalizaAIRezultat:
    cod_tip_document: str | None
    cont_financiar_id: str | None
    directie: str | None
    incredere: float
    rezumat: str
    text_extras: str
    campuri_extrase: dict = field(default_factory=dict)
    avertismente_extragere: list[str] = field(default_factory=list)
    dovezi: list[dict] = field(default_factory=list)
    segmente: list[dict] = field(default_factory=list)
    raspuns_provider_id: str | None = None
    tokeni_intrare: int | None = None
    tokeni_iesire: int | None = None


class ProviderAnalizaDocument(Protocol):
    nume: str
    model: str

    def analizeaza(self, context: ContextAnalizaDocument) -> AnalizaAIRezultat: ...
