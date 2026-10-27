from minio import Minio
from urllib3 import PoolManager, Timeout


class ObjectStorage:
    def __init__(self, settings):
        self.bucket = settings.minio_bucket
        self.client = Minio(
            settings.storage_address,
            access_key=settings.minio_access_key.get_secret_value(),
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_use_ssl,
            http_client=PoolManager(timeout=Timeout(connect=2, read=3), retries=False),
        )

    def ready(self):
        try:
            return self.client.bucket_exists(self.bucket)
        except Exception:
            return False
