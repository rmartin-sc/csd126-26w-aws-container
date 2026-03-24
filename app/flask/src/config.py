from . import aws

def get_param(name):
    """Get a parameter from AWS Systems Manager Parameter Store."""
    ssm = aws.client('ssm')
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    # There's a lot of information in the response, but we just want the value of the parameter, 
    # which is located at response['Parameter']['Value'].
    return response['Parameter']['Value']

class Config:
    """Configuration for the application."""

    SECRET_KEY = get_param('/app/flask/secret_key')

    COGNITO_USER_POOL_ID = get_param('/app/cognito/user_pool_id')
    # AWS's user pool domains are derived from the user pool ID 
    # by removing the underscore and converting to lowercase.
    COGNITO_USER_POOL_DOMAIN = COGNITO_USER_POOL_ID.replace('_', '').lower()
    COGNITO_CLIENT_ID = get_param('/app/cognito/client_id')
    COGNITO_CLIENT_SECRET = get_param('/app/cognito/client_secret')

    S3_BUCKET_NAME = get_param('/app/s3/photos_bucket_name')
    DYNAMODB_TABLE_NAME = get_param('/app/dynamodb/photos_table_name')

    # These URIs are constructed based on the user pool ID and the AWS region.
    # They are used by the app to know where to redirect users for authentication and where to redirect after logout.
    COGNITO_AUTH_URI = f'https://cognito-idp.{aws.REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}' 
    COGNITO_LOGOUT_URI = f'https://{COGNITO_USER_POOL_DOMAIN}.auth.{aws.REGION}.amazoncognito.com/logout'