"""DynamoDB backend for `DocumentStore`, the deployment target from the technical document."""

import json
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from producer_exchange.memory.store import Document, RevisionConflict, Write

_MAX_WRITES_PER_TRANSACTION = 100


class DynamoDBDocumentStore:
    def __init__(self, table_name: str, region: str) -> None:
        self._table_name = table_name
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def get(self, pk: str, sk: str) -> Document | None:
        item = self._table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")
        return self._live(item)

    def write_all(self, writes: list[Write]) -> list[Document]:
        if len(writes) > _MAX_WRITES_PER_TRANSACTION:
            raise ValueError(f"one atomic write is limited to {_MAX_WRITES_PER_TRANSACTION} documents")
        try:
            self._table.meta.client.transact_write_items(TransactItems=[self._as_put(write) for write in writes])
        except ClientError as error:
            if error.response["Error"]["Code"] == "TransactionCanceledException":
                raise RevisionConflict("an atomic write failed its revision checks") from error
            raise
        return [Document(w.pk, w.sk, w.body, w.expected_rev + 1, w.expires_at) for w in writes]

    def _as_put(self, write: Write) -> dict[str, Any]:
        item: dict[str, Any] = {
            "pk": write.pk,
            "sk": write.sk,
            "body": json.dumps(write.body, ensure_ascii=False),
            "rev": write.expected_rev + 1,
        }
        if write.expires_at is not None:
            item["expires_at"] = write.expires_at
        if write.expected_rev == 0:
            # DynamoDB removes expired items lazily, so an expired item still counts as absent here.
            condition = "attribute_not_exists(pk) OR expires_at <= :now"
            values: dict[str, Any] = {":now": int(time.time())}
        else:
            condition = "rev = :expected"
            values = {":expected": write.expected_rev}
        return {
            "Put": {
                "TableName": self._table_name,
                "Item": item,
                "ConditionExpression": condition,
                "ExpressionAttributeValues": values,
            }
        }

    def delete(self, pk: str, sk: str) -> None:
        self._table.delete_item(Key={"pk": pk, "sk": sk})

    def query(self, pk: str, sk_prefix: str = "") -> list[Document]:
        condition = Key("pk").eq(pk)
        if sk_prefix:
            condition &= Key("sk").begins_with(sk_prefix)
        documents: list[Document] = []
        kwargs: dict[str, Any] = {"KeyConditionExpression": condition, "ConsistentRead": True}
        while True:
            page = self._table.query(**kwargs)
            documents.extend(doc for doc in map(self._live, page["Items"]) if doc is not None)
            if "LastEvaluatedKey" not in page:
                return documents
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    @staticmethod
    def _live(item: dict[str, Any] | None) -> Document | None:
        if item is None:
            return None
        expires_at = int(item["expires_at"]) if "expires_at" in item else None
        if expires_at is not None and expires_at <= time.time():
            return None
        return Document(item["pk"], item["sk"], json.loads(item["body"]), int(item["rev"]), expires_at)


def create_table(table_name: str, region: str) -> None:
    """Create the single memory table with TTL enabled. CDK replaces this outside local testing."""
    client = boto3.client("dynamodb", region_name=region)
    client.create_table(
        TableName=table_name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    )
    client.get_waiter("table_exists").wait(TableName=table_name)
    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
    )


def delete_table(table_name: str, region: str) -> None:
    boto3.client("dynamodb", region_name=region).delete_table(TableName=table_name)
