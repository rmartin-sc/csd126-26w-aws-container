import boto3

REGION="us-east-1"

# This session object will be used to create client objects for different AWS services,
# and it will automatically use the AWS credentials that are available in the environment.
_session = boto3.session.Session(region_name=REGION)

def client(service_name):
    """Get a boto3 client for the specified AWS service."""
    return _session.client(service_name)