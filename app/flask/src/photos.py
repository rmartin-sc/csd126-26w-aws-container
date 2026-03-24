from datetime import datetime, timezone
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key

from src.config import Config


ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/heic": ".heic",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class PhotoNotFoundError(Exception):
    pass


class PhotoPermissionError(Exception):
    pass


s3 = boto3.client("s3", region_name=Config.REGION)
dynamodb = boto3.resource("dynamodb", region_name=Config.REGION)
photos_table = dynamodb.Table(Config.DYNAMODB_TABLE_NAME)


def _get_photo_or_raise(photo_id):
    response = photos_table.get_item(Key={"photo_id": photo_id})
    item = response.get("Item")
    if not item:
        raise PhotoNotFoundError("Photo not found")
    return item


def _assert_owner(item, user_id):
    if item.get("user_id") != user_id:
        raise PhotoPermissionError(
            "You do not have permission to modify this photo")


def upload_photo(user_id, username, file_obj, filename):
    mime_type = getattr(file_obj, "mimetype", None)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            "Unsupported file type. Allowed types: JPEG, HEIC, GIF, WebP")

    photo_id = str(uuid4())
    extension = ALLOWED_MIME_TYPES[mime_type]
    s3_key = f"photos/{user_id}/{photo_id}{extension}"
    uploaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if hasattr(file_obj, "stream") and hasattr(file_obj.stream, "seek"):
        file_obj.stream.seek(0)

    s3.upload_fileobj(
        file_obj,
        Config.S3_BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": mime_type},
    )

    item = {
        "photo_id": photo_id,
        "user_id": user_id,
        "username": username,
        "s3_key": s3_key,
        "uploaded_at": uploaded_at,
        "is_private": False,
        "status": "approved",
        "feed_key": "public",
    }
    photos_table.put_item(Item=item)

    return item


def delete_photo(photo_id, user_id):
    item = _get_photo_or_raise(photo_id)
    _assert_owner(item, user_id)

    s3.delete_object(Bucket=Config.S3_BUCKET_NAME, Key=item["s3_key"])
    photos_table.delete_item(Key={"photo_id": photo_id})


def toggle_privacy(photo_id, user_id):
    item = _get_photo_or_raise(photo_id)
    _assert_owner(item, user_id)

    new_is_private = not item.get("is_private", False)

    if new_is_private:
        response = photos_table.update_item(
            Key={"photo_id": photo_id},
            UpdateExpression="SET is_private = :is_private REMOVE feed_key",
            ExpressionAttributeValues={":is_private": True},
            ReturnValues="ALL_NEW",
        )
    else:
        response = photos_table.update_item(
            Key={"photo_id": photo_id},
            UpdateExpression="SET is_private = :is_private, feed_key = :feed_key",
            ExpressionAttributeValues={
                ":is_private": False, ":feed_key": "public"},
            ReturnValues="ALL_NEW",
        )

    return response.get("Attributes", {})


def get_user_photos(user_id):
    response = photos_table.query(
        IndexName="user-photos-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,
    )
    return response.get("Items", [])


def get_public_feed(limit=20):
    response = photos_table.query(
        IndexName="feed-index",
        KeyConditionExpression=Key("feed_key").eq("public"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])


def get_presigned_url(s3_key, expiry=3600):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": Config.S3_BUCKET_NAME, "Key": s3_key},
        ExpiresIn=expiry,
    )
