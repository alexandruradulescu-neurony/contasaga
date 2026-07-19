from django.core import checks
from django.test import SimpleTestCase, override_settings

from core.checks import production_configuration_checks


class ProductionConfigurationCheckTests(SimpleTestCase):
    @override_settings(RELEASE_ENVIRONMENT="development")
    def test_checks_are_not_applied_to_local_development(self):
        self.assertEqual(production_configuration_checks(None), [])

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="local",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
        ALLOWED_HOSTS=["localhost"],
        CSRF_TRUSTED_ORIGINS=[],
        EMAIL_HOST="localhost",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@localhost>",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DOCUMENT_OCR_ENABLED=False,
    )
    def test_unsafe_production_configuration_is_blocked(self):
        result = production_configuration_checks(None)
        self.assertEqual(
            {message.id for message in result},
            {"core.E001", "core.E002", "core.E003", "core.E004", "core.E005", "core.E007"},
        )
        self.assertTrue(all(message.level == checks.ERROR for message in result))

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="r2",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="localhost",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@example.test>",
        ALLOWED_HOSTS=["app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
        CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}},
        DOCUMENT_OCR_ENABLED=False,
    )
    def test_production_smtp_requires_an_explicit_host(self):
        self.assertEqual(
            {message.id for message in production_configuration_checks(None)},
            {"core.E006"},
        )

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="r2",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        ALLOWED_HOSTS=["app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@example.test>",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}},
        DOCUMENT_OCR_ENABLED=False,
    )
    def test_safe_production_shape_passes_custom_checks(self):
        self.assertEqual(production_configuration_checks(None), [])

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="r2",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        ALLOWED_HOSTS=["app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@example.test>",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}},
        LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS=0,
        DOCUMENT_DOWNLOAD_URL_TTL=7200,
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=True,
        DOCUMENT_OCR_ENABLED=False,
    )
    def test_invalid_security_limits_are_blocked(self):
        self.assertEqual(
            {message.id for message in production_configuration_checks(None)},
            {"core.E009", "core.E010", "core.E011"},
        )

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="r2",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        ALLOWED_HOSTS=["app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@example.test>",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}},
        DOCUMENT_AI_ENABLED=True,
        DOCUMENT_AI_PROVIDER="openai",
        DOCUMENT_AI_MODEL="gpt-5.6-luna",
        DOCUMENT_AI_TIMEOUT_SECONDS=120,
        OPENAI_API_KEY="",
        DOCUMENT_OCR_ENABLED=False,
    )
    def test_enabled_document_ai_requires_provider_credential(self):
        self.assertEqual(
            {message.id for message in production_configuration_checks(None)},
            {"core.E013"},
        )

    @override_settings(
        RELEASE_ENVIRONMENT="production",
        DOCUMENT_STORAGE_BACKEND="r2",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        ALLOWED_HOSTS=["app.example.test"],
        CSRF_TRUSTED_ORIGINS=["https://app.example.test"],
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="Conta Saga <no-reply@example.test>",
        CACHES={"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache"}},
        DOCUMENT_OCR_ENABLED=True,
        DOCUMENT_OCR_COMMAND="missing-tesseract",
        DOCUMENT_OCR_LANGUAGES="ron+eng",
        DOCUMENT_OCR_TIMEOUT_SECONDS=60,
        DOCUMENT_OCR_MIN_TEXT_CHARS=40,
    )
    def test_enabled_ocr_requires_runtime_binary(self):
        self.assertEqual(
            {message.id for message in production_configuration_checks(None)},
            {"core.E017"},
        )
