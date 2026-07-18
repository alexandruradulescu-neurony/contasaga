from typing import Any


class DefaultDatabaseRouter:
    """Routează implicit tot ORM-ul spre conexiunea protejată de RLS.

    Apelurile explicite `.using("privileged")` ocolesc routerul și sunt permise
    numai în service layer. Regula închide rutarea sticky a instanțelor citite
    în timpul autentificării.
    """

    application_aliases = {"default", "privileged"}

    def db_for_read(self, model: type, **hints: Any) -> str:
        return "default"

    def db_for_write(self, model: type, **hints: Any) -> str:
        return "default"

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        db1 = obj1._state.db or "default"
        db2 = obj2._state.db or "default"
        if db1 in self.application_aliases and db2 in self.application_aliases:
            return True
        return None

    def allow_migrate(
        self,
        db: str,
        app_label: str,
        model_name: str | None = None,
        **hints: Any,
    ) -> bool:
        return db == "default"
