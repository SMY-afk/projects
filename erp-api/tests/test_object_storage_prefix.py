from urllib.parse import parse_qs, urlsplit

import pytest

from erp_api.services.object_storage import S3ObjectStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.upload_options: dict[str, object] = {}

    def put_object(self, *, Bucket, Key, **kwargs):
        self.calls.append(("put", Key))
        self.upload_options = kwargs

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Key))
        return {"Body": FakeBody(), "ContentType": "image/png"}

    def delete_object(self, *, Bucket, Key):
        self.calls.append(("delete", Key))

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.calls.append(("presign", Params["Key"]))
        return f"https://objects.test/{Params['Key']}?signed=1"


class FakeBody:
    def read(self) -> bytes:
        return b"image"

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_s3_storage_applies_prefix_to_every_object_operation(monkeypatch) -> None:
    client = FakeS3Client()
    monkeypatch.setattr(
        "erp_api.services.object_storage.boto3.client", lambda *a, **kw: client
    )
    storage = S3ObjectStorage(
        endpoint_url="https://oss.test",
        region="cn-shenzhen",
        access_key="test-access",
        secret_key="test-secret",
        bucket="shared-bucket",
        force_path_style=False,
        key_prefix="erp/",
    )

    await storage.put(
        "sample/creator-avatars/avatar.png",
        b"image",
        content_type="image/png",
        metadata={},
    )
    stored = await storage.get("sample/creator-avatars/avatar.png")
    url = await storage.presign_get(
        "sample/creator-avatars/avatar.png", expires_seconds=900
    )
    await storage.delete("sample/creator-avatars/avatar.png")

    assert stored.body == b"image"
    assert client.upload_options["ACL"] == "private"
    assert client.calls == [
        ("put", "erp/sample/creator-avatars/avatar.png"),
        ("get", "erp/sample/creator-avatars/avatar.png"),
        ("presign", "erp/sample/creator-avatars/avatar.png"),
        ("delete", "erp/sample/creator-avatars/avatar.png"),
    ]
    assert "/erp/sample/creator-avatars/avatar.png" in url


def test_s3_storage_rejects_unsafe_prefix(monkeypatch) -> None:
    monkeypatch.setattr(
        "erp_api.services.object_storage.boto3.client", lambda *a, **kw: FakeS3Client()
    )
    with pytest.raises(ValueError, match="prefix"):
        S3ObjectStorage(
            endpoint_url=None,
            region="cn-shenzhen",
            access_key="test-access",
            secret_key="test-secret",
            bucket="shared-bucket",
            force_path_style=False,
            key_prefix="../video/",
        )


@pytest.mark.asyncio
async def test_s3_storage_uses_virtual_host_for_oss() -> None:
    storage = S3ObjectStorage(
        endpoint_url="https://s3.oss-cn-shenzhen.aliyuncs.com",
        region="cn-shenzhen",
        access_key="test-access",
        secret_key="test-secret",
        bucket="wjvedio",
        force_path_style=False,
        key_prefix="erp/",
    )

    url = await storage.presign_get("probe.txt", expires_seconds=60)

    assert urlsplit(url).hostname == "wjvedio.s3.oss-cn-shenzhen.aliyuncs.com"
    assert urlsplit(url).path == "/erp/probe.txt"
    assert "AWSAccessKeyId" in parse_qs(urlsplit(url).query)


@pytest.mark.asyncio
async def test_s3_storage_keeps_explicit_path_style() -> None:
    storage = S3ObjectStorage(
        endpoint_url="https://storage.example.com",
        region="cn-shenzhen",
        access_key="test-access",
        secret_key="test-secret",
        bucket="shared-bucket",
        force_path_style=True,
    )

    url = await storage.presign_get("probe.txt", expires_seconds=60)

    assert urlsplit(url).hostname == "storage.example.com"
    assert urlsplit(url).path == "/shared-bucket/probe.txt"
    assert "X-Amz-Algorithm" in parse_qs(urlsplit(url).query)
