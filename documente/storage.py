import json
import os
import secrets
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from django.conf import settings


class EroareStorage(Exception):
    pass


@dataclass(frozen=True)
class MetadataObiect:
    dimensiune: int
    content_type: str | None


class LocalDocumentStorage:
    is_local = True

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or settings.DOCUMENT_LOCAL_STORAGE_ROOT).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise EroareStorage("Cheie de stocare invalidă.")
        return path

    def _metadata_path(self, key: str) -> Path:
        return self._path(f"{key}.metadata.json")

    def _temporary_path(self, path: Path) -> Path:
        return path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")

    def _ensure_private_parent(self, path: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        current = self.root
        for component in path.parent.relative_to(self.root).parts:
            current /= component
            current.mkdir(exist_ok=True, mode=0o700)
            current.chmod(0o700)

    def _write_metadata(self, key: str, content_type: str) -> None:
        metadata_path = self._metadata_path(key)
        self._ensure_private_parent(metadata_path)
        temporar = self._temporary_path(metadata_path)
        try:
            temporar.write_text(
                json.dumps({"content_type": content_type}),
                encoding="utf-8",
            )
            temporar.chmod(0o600)
            os.replace(temporar, metadata_path)
        finally:
            temporar.unlink(missing_ok=True)

    def put_bytes(self, key: str, continut: bytes, content_type: str) -> None:
        path = self._path(key)
        self._ensure_private_parent(path)
        temporar = self._temporary_path(path)
        try:
            temporar.write_bytes(continut)
            temporar.chmod(0o600)
            os.replace(temporar, path)
        finally:
            temporar.unlink(missing_ok=True)
        self._write_metadata(key, content_type)

    def put_archive_bytes(self, key: str, continut: bytes, content_type: str) -> None:
        """Write a human-facing archive file without visible metadata sidecars."""
        path = self._path(key)
        self._ensure_private_parent(path)
        temporar = self._temporary_path(path)
        try:
            temporar.write_bytes(continut)
            temporar.chmod(0o600)
            os.replace(temporar, path)
        finally:
            temporar.unlink(missing_ok=True)
        self._metadata_path(key).unlink(missing_ok=True)

    def put_file(self, key: str, sursa: Path | str, content_type: str) -> None:
        path = self._path(key)
        self._ensure_private_parent(path)
        temporar = self._temporary_path(path)
        try:
            shutil.copyfile(sursa, temporar)
            temporar.chmod(0o600)
            os.replace(temporar, path)
        finally:
            temporar.unlink(missing_ok=True)
        self._write_metadata(key, content_type)

    def head(self, key: str) -> MetadataObiect:
        path = self._path(key)
        if not path.is_file():
            raise EroareStorage("Fișierul încărcat nu există.")
        content_type = None
        metadata_path = self._metadata_path(key)
        if metadata_path.is_file():
            try:
                content_type = json.loads(metadata_path.read_text(encoding="utf-8")).get(
                    "content_type"
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise EroareStorage("Metadatele fișierului sunt corupte.") from exc
        return MetadataObiect(dimensiune=path.stat().st_size, content_type=content_type)

    def read_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise EroareStorage("Fișierul încărcat nu există.")
        return path.read_bytes()

    def open_binary(self, key: str):
        path = self._path(key)
        if not path.is_file():
            raise EroareStorage("Fișierul încărcat nu există.")
        return path.open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
        self._metadata_path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix.rstrip("/"))
        if path == self.root:
            raise EroareStorage("Prefixul de ștergere nu poate fi rădăcina storage-ului.")
        if path.exists() and not path.is_dir():
            raise EroareStorage("Prefixul de ștergere nu este un director.")
        shutil.rmtree(path, ignore_errors=True)

    def healthcheck(self) -> None:
        verificat = self.root
        while not verificat.exists() and verificat != verificat.parent:
            verificat = verificat.parent
        if not verificat.is_dir() or not os.access(verificat, os.W_OK):
            raise EroareStorage("Storage-ul local nu este accesibil pentru scriere.")


class R2DocumentStorage:
    is_local = False

    def __init__(self):
        configurare = {
            "R2_ACCOUNT_ID": settings.R2_ACCOUNT_ID,
            "R2_ACCESS_KEY_ID": settings.R2_ACCESS_KEY_ID,
            "R2_SECRET_ACCESS_KEY": settings.R2_SECRET_ACCESS_KEY,
            "R2_BUCKET_NAME": settings.R2_BUCKET_NAME,
        }
        lipsesc = [nume for nume, valoare in configurare.items() if not valoare]
        if lipsesc:
            raise EroareStorage(f"Lipsesc setările R2: {', '.join(lipsesc)}")
        self.bucket = settings.R2_BUCKET_NAME
        self.client = boto3.client(
            service_name="s3",
            endpoint_url=(f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"),
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )

    def presigned_put_url(self, key: str, content_type: str) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.DOCUMENT_UPLOAD_URL_TTL,
        )

    def presigned_get_url(
        self,
        key: str,
        *,
        content_type: str,
        content_disposition: str,
    ) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": content_disposition,
            },
            ExpiresIn=settings.DOCUMENT_DOWNLOAD_URL_TTL,
        )

    def put_bytes(self, key: str, continut: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=continut,
            ContentType=content_type,
        )

    def put_archive_bytes(self, key: str, continut: bytes, content_type: str) -> None:
        self.put_bytes(key, continut, content_type)

    def put_file(self, key: str, sursa: Path | str, content_type: str) -> None:
        self.client.upload_file(
            str(sursa),
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def head(self, key: str) -> MetadataObiect:
        try:
            raspuns = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise EroareStorage("Fișierul încărcat nu există în R2.") from exc
        return MetadataObiect(
            dimensiune=raspuns["ContentLength"],
            content_type=raspuns.get("ContentType"),
        )

    def read_bytes(self, key: str) -> bytes:
        try:
            raspuns = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise EroareStorage("Fișierul încărcat nu există în R2.") from exc
        body = raspuns["Body"]
        try:
            return body.read(settings.DOCUMENT_UPLOAD_MAX_BYTES + 1)
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        prefix = prefix.strip("/")
        if not prefix:
            raise EroareStorage("Prefixul de ștergere nu poate fi rădăcina storage-ului.")
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for pagina in paginator.paginate(Bucket=self.bucket, Prefix=f"{prefix}/"):
                obiecte = [{"Key": item["Key"]} for item in pagina.get("Contents", [])]
                if obiecte:
                    self.client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": obiecte, "Quiet": True},
                    )
        except ClientError as exc:
            raise EroareStorage("Prefixul arhivei nu a putut fi curățat din R2.") from exc

    def healthcheck(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            raise EroareStorage("Bucket-ul R2 nu este accesibil.") from exc


@lru_cache(maxsize=1)
def get_document_storage():
    if settings.DOCUMENT_STORAGE_BACKEND == "local":
        return LocalDocumentStorage()
    if settings.DOCUMENT_STORAGE_BACKEND == "r2":
        return R2DocumentStorage()
    raise EroareStorage(f"Backend de stocare necunoscut: {settings.DOCUMENT_STORAGE_BACKEND}")
