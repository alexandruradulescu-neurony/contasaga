from django.apps import AppConfig


class ConturiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "conturi"

    def ready(self) -> None:
        from django.contrib.auth.models import update_last_login
        from django.contrib.auth.signals import user_logged_in

        # Conexiunea web nu are voie să scrie această coloană. Backend-ul de
        # autentificare o actualizează explicit prin serviciul privilegiat.
        user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
