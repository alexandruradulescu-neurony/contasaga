from django import template

register = template.Library()

STATUS_LABELS = {
    "deschisa": "Deschisă",
    "documente_incomplete": "Documente incomplete",
    "gata_pentru_verificare": "Gata pentru verificare",
    "in_lucru": "În lucru",
    "inchisa": "Închisă",
    "draft": "Ciornă",
    "trimis": "Trimis",
    "in_verificare": "În verificare",
    "necesita_clarificari": "Necesită clarificări",
    "acceptat": "Acceptat",
    "procesat": "Procesat",
    "arhivat": "Arhivat",
    "anulat": "Anulat",
    "lipsa": "Lipsă",
    "partial": "Parțial",
    "primit": "Primit",
    "nu_se_aplica": "Nu se aplică",
}

LUNI = {
    1: "Ianuarie",
    2: "Februarie",
    3: "Martie",
    4: "Aprilie",
    5: "Mai",
    6: "Iunie",
    7: "Iulie",
    8: "August",
    9: "Septembrie",
    10: "Octombrie",
    11: "Noiembrie",
    12: "Decembrie",
}


@register.filter
def status_label(value):
    if value in (None, ""):
        return "Creat"
    return STATUS_LABELS.get(str(value), str(value).replace("_", " ").capitalize())


@register.filter
def luna_nume(value):
    try:
        return LUNI.get(int(value), value)
    except (TypeError, ValueError):
        return value
