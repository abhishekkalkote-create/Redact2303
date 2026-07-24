from app.storage.base import ContentStore


class S3Store(ContentStore):
    """Real content bucket (infra/modules/storage's `{name}-content` bucket). Not wired
    until an AWS account exists — see api/app/storage/__init__.py's get_store()."""

    def __init__(self, bucket: str, region: str) -> None:
        import boto3  # imported lazily so boto3 isn't required for local-only dev runs

        self.bucket = bucket
        self._client = boto3.client("s3", region_name=region)

    def put(self, org_id: str, key: str, data: bytes) -> str:
        full_key = f"{org_id}/{key}"
        self._client.put_object(Bucket=self.bucket, Key=full_key, Body=data)
        return full_key

    def get(self, org_id: str, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=f"{org_id}/{key}")
        return resp["Body"].read()

    def exists(self, org_id: str, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=f"{org_id}/{key}")
            return True
        except ClientError:
            return False

    def delete(self, org_id: str, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=f"{org_id}/{key}")
