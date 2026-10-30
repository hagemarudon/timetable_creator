"""保存先（手元のフォルダ / Google Cloud Storage）。

クラウドでは塾ごとの条件などを「jukus/<塾ID>/…」に分けて保存する。
保存先は環境変数 TIMETABLE_STORE で選ぶ：「gs://バケット名」なら Cloud Storage、それ以外はフォルダのパス。
"""
from __future__ import annotations

import os
from pathlib import Path


class LocalStore:
    """手元のフォルダに保存する（開発用・Macで動かすとき）。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"保存先の外は使えません：{key}")
        return p

    def get(self, key: str) -> str | None:
        p = self._path(key)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def put(self, key: str, text: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class GCSStore:
    """Google Cloud Storage のバケットに保存する（Cloud Run で動かすとき）。"""

    def __init__(self, bucket: str, prefix: str = ""):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def get(self, key: str) -> str | None:
        blob = self.bucket.blob(self.prefix + key)
        return blob.download_as_text(encoding="utf-8") if blob.exists() else None

    def put(self, key: str, text: str) -> None:
        self.bucket.blob(self.prefix + key).upload_from_string(text, content_type="text/plain; charset=utf-8")


def open_store(spec: str | None = None, default: str | Path = "data"):
    """TIMETABLE_STORE（または spec）から保存先を作る。"""
    spec = spec or os.environ.get("TIMETABLE_STORE") or str(default)
    if spec.startswith("gs://"):
        bucket, _, prefix = spec[len("gs://"):].partition("/")
        return GCSStore(bucket, prefix)
    return LocalStore(spec)
