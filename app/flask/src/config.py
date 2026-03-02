import boto3
from dotenv import load_dotenv

load_dotenv()

def get_param(name):
    """Get a parameter from AWS Systems Manager Parameter Store."""
    ssm = boto3.client('ssm', region_name='us-east-1')
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    # There's a lot of information in the response, but we just want the value of the parameter, which is located at response['Parameter']['Value'].
    return response['Parameter']['Value']

class Config:
    """Configuration for the application."""

    REGION = boto3.session.Session().region_name

    SECRET_KEY = get_param('/app/flask/secret_key')

    COGNITO_USER_POOL_ID = get_param('/app/cognito/user_pool_id')
    COGNITO_USER_POOL_DOMAIN = COGNITO_USER_POOL_ID.replace('_', '').lower()
    COGNITO_CLIENT_ID = get_param('/app/cognito/client_id')
    COGNITO_CLIENT_SECRET = get_param('/app/cognito/client_secret')

    COGNITO_AUTH_URI = f'https://cognito-idp.{REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}' 
    COGNITO_LOGOUT_URI = f'https://{COGNITO_USER_POOL_DOMAIN}.auth.{REGION}.amazoncognito.com/logout'