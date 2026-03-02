import boto3

REGION="us-east-1"

_session = boto3.session.Session(region_name=REGION)

def client(service_name):
    """Get a boto3 client for the specified AWS service."""
    return _session.client(service_name)