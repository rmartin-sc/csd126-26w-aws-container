"""Main application file for the Flask app."""
from flask import Flask, render_template, request, redirect, url_for, session, flash
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode

from src.config import Config

app = Flask(__name__)            # Initialize Flask app
app.config.from_object(Config)   # Load in the configuration from config.py

# Uncomment this line to print the loaded configuration for debugging purposes
# print(f"Loaded configuration: {app.config}")

# Initialize OAuth with the Flask app and register the Cognito OIDC provider
oauth = OAuth(app)
oauth.register(
  name='oidc',
  authority=app.config['COGNITO_AUTH_URI'],
  client_id=app.config['COGNITO_CLIENT_ID'],
  client_secret=app.config['COGNITO_CLIENT_SECRET'],
  server_metadata_url=f"{app.config['COGNITO_AUTH_URI']}/.well-known/openid-configuration",
  client_kwargs={'scope': 'email openid'}
)

# These @app.route annotations define the different URLs in our app.
# The index() function renders the home page, which is defined in templates/index.html.
@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@app.route('/login')
def login():
    """Login page"""
    # Here, we redirect to the Cognito-hosted UI for authentication,
    # and specify the callback URL to be /authorize, 
    # which Cognito will redirect to after successful authentication.
    return oauth.oidc.authorize_redirect(url_for('authorize', _external=True))

@app.route('/authorize')
def authorize():
    """The callback endpoint for Cognito authentication"""
    # After the user successfully logs in through the Cognito-hosted UI, 
    # Cognito will redirect back to this endpoint with an authorization code.
    # Here, we retrieve the access token and ID token that Cognito sends back,
    # and then we can extract the user's information from the ID token.
    token = oauth.oidc.authorize_access_token()
    user = token['userinfo']
    # The session object is a special object provided by Flask that allows us 
    # to store information about the logged-in user's session.
    session['user'] = user
    # Uncomment this line to print the user information for debugging purposes
    # print(f"User info from Cognito: {user}")
    session['display_name'] = user['cognito:username']
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Logout"""
    # To log the user out, we simply...

    # 1) clear their session information in the Flask app
    session.pop('user', None)
    session.pop('display_name', None)
    flash('You have been logged out.', 'info')

    params = urlencode({
        'client_id': app.config['COGNITO_CLIENT_ID'],
        # After logging out of Cognito, we want to redirect the user back to our app's home page, 
        # which is located at the URL for the index() function.
        'logout_uri': url_for('index', _external=True)
    })
    cognito_logout_url = f"{app.config['COGNITO_LOGOUT_URI']}?{params}"

    # 2) redirect them to the Cognito logout endpoint, 
    # which will log them out of their Cognito session as well, then
    # redirect them back to our app's home page after logging out of Cognito.
    # (See the note in the cognito_logout_url and params variables above)
    return redirect(cognito_logout_url)

@app.route('/profile')
def profile():
    """Profile page"""
    # This is a protected page that only logged-in users should be able to access.
    # If the user is not logged in (i.e. they don't have a 'user' key in their session), 
    # then we redirect them to the login page.
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # If the user is logged in, we render the profile page, which is defined in templates/profile.html.
    return render_template('profile.html', user=session['user'])