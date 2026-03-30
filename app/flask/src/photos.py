from datetime import datetime, timezone
from uuid import uuid4

from . import aws
from boto3.dynamodb.conditions import Key # This is used to build KeyConditionExpressions for DynamoDB queries.

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


s3 = aws.client("s3")
photos_table = aws.dynamodb_table(Config.DYNAMODB_TABLE_NAME)


def _get_photo_or_raise(photo_id):
    """Helper function to get a photo item from DynamoDB or raise an error if it doesn't exist."""
    response = photos_table.get_item(Key={"photo_id": photo_id})
    item = response.get("Item")
    if not item:
        raise PhotoNotFoundError("Photo not found")
    return item


def _assert_owner(item, user_id):
    """Helper function to check if the given user_id is the owner of the photo item."""
    if item.get("user_id") != user_id:
        raise PhotoPermissionError(
            "You do not have permission to modify this photo")


def upload_photo(user_id, username, file_obj, filename):
    """Upload a photo to S3 and create a record in DynamoDB."""
    mime_type = getattr(file_obj, "mimetype", None)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            "Unsupported file type. Allowed types: JPEG, HEIC, GIF, WebP")

    photo_id = str(uuid4()) # A universally unique identifier for the photo, which will be used as the primary key in DynamoDB and part of the S3 key.
    extension = ALLOWED_MIME_TYPES[mime_type]
    s3_key = f"photos/{user_id}/{photo_id}{extension}"
    uploaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # If the file object has a stream that supports seeking, 
    # we need to reset it to the beginning before uploading to S3.
    # This is important because the file object might have been read or processed before, 
    # and the stream position could be at the end, which would result in an empty upload.
    if hasattr(file_obj, "stream") and hasattr(file_obj.stream, "seek"):
        file_obj.stream.seek(0)

    # This calls the AWS SDK (via boto3) to upload the file object to the specified S3 bucket and key
    s3.upload_fileobj(
        file_obj,
        Config.S3_BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": mime_type},
    )

    # Now we build the item to be stored in DynamoDB, which includes 
    # metadata about the photo and its location in S3.
    item = {
        "photo_id": photo_id,
        "user_id": user_id,    # So we can query photos by user and enforce permissions
        "username": username,  # This is just for convenience so we can display the username in the feed without needing to look it up in Cognito
        "s3_key": s3_key,
        "uploaded_at": uploaded_at,
        "is_private": False,   # Default to public, but users can toggle this later.
        "status": "approved",  # Looking ahead, we might have a 'pending' status until moderation via a Lambda function that checks for inappropriate content. For now, we'll just set it to 'approved'.
        "feed_key": "public",  # This is a field that allows us to efficiently query for public photos in the feed. 
                               # If the photo is private or not approved, we will remove this field.
    }
    # Call the AWS SDK to put the item into the DynamoDB table, 
    # which will create a new record for this photo.
    photos_table.put_item(Item=item)

    return item


def delete_photo(photo_id, user_id):
    """Delete a photo from S3 and remove its corresponding record from DynamoDB."""
    item = _get_photo_or_raise(photo_id)
    # Only the owner of the photo can delete it
    _assert_owner(item, user_id) 

    s3.delete_object(Bucket=Config.S3_BUCKET_NAME, Key=item["s3_key"])
    photos_table.delete_item(Key={"photo_id": photo_id})


def toggle_privacy(photo_id, user_id):
    """Toggle the privacy setting of a photo. If it's currently public, make it private, and vice versa."""
    item = _get_photo_or_raise(photo_id)
    # Only the owner of the photo can change its privacy setting
    _assert_owner(item, user_id)

    new_is_private = not item.get("is_private", False)

    # When a photo is made private, or the status is not 'approved', 
    # we remove the 'feed_key' attribute so it won't appear in the public feed.
    if new_is_private or item.get("status") != "approved":
        response = photos_table.update_item(
            Key={"photo_id": photo_id},
            # This 'UpdateExpression' tells DynamoDB to set the 'is_private' 
            # attribute to True and remove the 'feed_key' attribute from the item.
            UpdateExpression="SET is_private = :is_private REMOVE feed_key",
            # 'ExpressionAttributeValues' provides the actual value for the 
            # ':is_private' placeholder used in the UpdateExpression.
            # This is a common pattern in DynamoDB updates where you use placeholders 
            # in the expression and then provide the actual values separately 
            # to avoid issues with reserved keywords and injection attacks.
            ExpressionAttributeValues={":is_private": new_is_private},
            ReturnValues="ALL_NEW",
        )
    else:
        response = photos_table.update_item(
            Key={"photo_id": photo_id},
            # When making the photo public, we set 'is_private' to False and also set 'feed_key' to "public" so that it will appear in the public feed queries. 
            UpdateExpression="SET is_private = :is_private, feed_key = :feed_key",
            # Here we provide values for both ':is_private' and ':feed_key'.
            # We got here because new_is_private is False (the photo is being made public)
            # AND the status is 'approved', which means we want to add it back to 
            # the public feed by setting 'feed_key' to "public".
            ExpressionAttributeValues={
                    ":is_private": False, 
                    ":feed_key": "public"
                },
            ReturnValues="ALL_NEW",
        )

    return response.get("Attributes", {})


def get_user_photos(user_id):
    """Get all photos uploaded by a specific user, ordered by upload time descending."""
    response = photos_table.query(
        IndexName="user-photos-index",
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False,  # This tells DynamoDB to return the results in descending order based on the sort key, which is 'uploaded_at' in our case. This way, the most recently uploaded photos will appear first.
    )
    return response.get("Items", [])


def get_public_feed(limit=20):
    """Get the most recent public photos for the feed, ordered by upload time descending."""
    response = photos_table.query(
        IndexName="feed-index",
        KeyConditionExpression=Key("feed_key").eq("public"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])


def get_presigned_url(s3_key, expiry=3600):
    """Generate a presigned URL for accessing a photo in S3. 
    The URL will expire after the specified number of seconds (default is 1 hour).
    This function must ONLY be called for photos that the authenticated user has 
    permission to view (e.g. their own photos or public photos).
    """
    # This function uses the AWS SDK to generate a 'presigned URL' for the given S3 key.
    # A presigned URL is a URL that includes temporary credentials in the URL itself,
    # allowing ANYONE with the URL to access it, even if the bucket is private.
    # It is important to understand that the security of this approach relies on the fact 
    # that the presigned URL is ONLY generated for photos that the user has permission 
    # to view, and that the URL expires after a reasonable amount of time. 
    # This way, we can keep our S3 bucket private and secure, while still allowing users 
    # to access their photos and public photos through the app.
    # Effectively, we are putting the onus on our app server to enforce the access control 
    # rules (e.g. only generate presigned URLs for photos the user is allowed to see),
    # while S3 is just responsible for securely serving the files when accessed via 
    # the presigned URL.
    #
    # How it works:
    # When this call is made, AWS cryptographically signs the URL based on app server's 
    # AWS credentials and the specified expiry time. The generated URL contains 
    # temporary credentials (in the query portion of the URL) 
    # that allow anyone with the URL to access the S3 object directly.
    # When someone tries to access the URL, S3 checks the signature and the expiry time. 
    # If the signature is valid and the URL has not expired, S3 serves the file. 
    # If the signature is invalid or the URL has expired, S3 returns an error.
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": Config.S3_BUCKET_NAME, "Key": s3_key},
        ExpiresIn=expiry,
    )
