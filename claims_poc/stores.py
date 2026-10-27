"""Document storage (Azure Blob) and audit storage (Cosmos DB), each with a local fallback for development."""
from __future__ import annotations

import json
import os
from pathlib import Path


# ---------------- documents ----------------
class LocalBlobStore:
    def __init__(self, root: str | Path = "./local_blobs"):
        self.root = Path(root)

    def put(self, claim_id: str, filename: str, data: bytes) -> str:
        name = f"{claim_id}/{filename}"
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return name

    def get(self, blob_name: str) -> bytes:
        return (self.root / blob_name).read_bytes()


class AzureBlobStore:
    def __init__(self, conn_str: str, container: str):
        from azure.storage.blob import BlobServiceClient
        self.container = BlobServiceClient.from_connection_string(conn_str).get_container_client(container)
        if not self.container.exists():
            self.container.create_container()

    def put(self, claim_id: str, filename: str, data: bytes) -> str:
        name = f"{claim_id}/{filename}"
        self.container.upload_blob(name, data, overwrite=True)
        return name

    def get(self, blob_name: str) -> bytes:
        return self.container.download_blob(blob_name).readall()


# ---------------- audit trail ----------------
class LocalAuditStore:
    def __init__(self, root: str | Path = "./local_audit"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, claim_id: str, doc: dict):
        (self.root / f"{claim_id}.json").write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")

    def get(self, claim_id: str):
        p = self.root / f"{claim_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class CosmosAuditStore:
    """One JSON document per claim: extracted fields, every agent's findings, token usage. Partition key: /claim_id."""

    def __init__(self, endpoint: str, key: str | None, database: str, container: str):
        from azure.cosmos import CosmosClient, PartitionKey
        credential = key
        if not credential:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        db = CosmosClient(endpoint, credential=credential).create_database_if_not_exists(database)
        self.container = db.create_container_if_not_exists(id=container, partition_key=PartitionKey(path="/claim_id"))

    def save(self, claim_id: str, doc: dict):
        item = json.loads(json.dumps(doc, default=str))  # make sure everything is plain JSON
        item["id"], item["claim_id"] = claim_id, claim_id
        self.container.upsert_item(item)

    def get(self, claim_id: str):
        try:
            return self.container.read_item(item=claim_id, partition_key=claim_id)
        except Exception:
            return None


def make_blob_store():
    cs = os.getenv("AZURE_STORAGE_CONN_STR")
    return AzureBlobStore(cs, os.getenv("BLOB_CONTAINER", "claim-documents")) if cs else LocalBlobStore()


def make_audit_store():
    ep = os.getenv("COSMOS_ENDPOINT")
    if ep:
        return CosmosAuditStore(ep, os.getenv("COSMOS_KEY"), os.getenv("COSMOS_DB", "claims"), os.getenv("COSMOS_CONTAINER", "audit"))
    return LocalAuditStore()
