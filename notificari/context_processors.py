from .models import Notificare


def notificari_necitite(request):
    if not request.user.is_authenticated:
        return {"numar_notificari_necitite": 0}
    return {
        "numar_notificari_necitite": Notificare.objects.filter(
            citita=False,
            vizibila_in_app=True,
        ).count(),
    }
