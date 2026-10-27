from unittest.mock import Mock

from app.storage import ObjectStorage


def test_bucket_unavailable_does_not_claim_ready(settings):
    storage = ObjectStorage(settings)
    storage.client = Mock()
    storage.client.bucket_exists.side_effect = ConnectionError("synthetic outage")
    assert storage.ready() is False
    storage.client.bucket_exists.side_effect = None
    storage.client.bucket_exists.return_value = False
    assert storage.ready() is False
