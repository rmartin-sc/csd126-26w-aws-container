"""Main application file for the Flask app."""
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode

from src.config import Config
from src import photos

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Uncommentk this line to print the loaded configuration for debugging purposes
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

# Here we define a 'decorator' function that we can use to annotate
# any route that we want to require the user to be logged in to access.
# The @wraps(func) decorator is a helper that preserves the original 
# function's metadata (like its name and docstring) when we wrap it with 
# our own logic.
def login_required(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
                if 'user' not in session:
                        return redirect(url_for('login'))
                return func(*args, **kwargs)

        return wrapper

# These @app.route annotations define the different URLs in our app.
# The index() function renders the home page, which is defined in templates/index.html.
@app.route('/')
def index():
    """Home page"""
    feed_photos = photos.get_public_feed()
    for item in feed_photos:
        item['image_url'] = photos.get_presigned_url(item['s3_key'])
    return render_template('index.html', photos=feed_photos)

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
        "client_id": app.config['COGNITO_CLIENT_ID'],
        # After logging out of Cognito, we want to redirect the user back to our app's home page, 
        # which is located at the URL for the index() function.
        "logout_uri": url_for('index', _external=True)
    })
    cognito_logout_url = f"{app.config['COGNITO_LOGOUT_URI']}?{params}"

    # 2) redirect them to the Cognito logout endpoint, 
    # which will log them out of their Cognito session as well, then
    # redirect them back to our app's home page after logging out of Cognito.
    # (See the note in the cognito_logout_url and params variables above)
    return redirect(cognito_logout_url)

@app.route('/profile')
@login_required
def profile():
    """Profile page"""
    # If the user is logged in, we render the profile page, which is defined in templates/profile.html.
    user = session['user']
    user_photos = photos.get_user_photos(user['sub'])
    for item in user_photos:
        item['image_url'] = photos.get_presigned_url(item['s3_key'])
    return render_template('profile.html', user=user, photos=user_photos)


@app.route('/upload', methods=['GET'])
@login_required
def upload_page():
    """Upload page"""
    return render_template('upload.html')


@app.route('/upload', methods=['POST'])
@login_required
def upload_photo():
    """Upload a photo"""
    max_bytes = 5 * 1024 * 1024
    if request.content_length and request.content_length > max_bytes:
        flash('Upload exceeds 5 MB limit.', 'danger')
        return redirect(url_for('upload_page'))

    file_obj = request.files.get('photo')
    if not file_obj or not file_obj.filename:
        flash('Please choose an image file to upload.', 'warning')
        return redirect(url_for('upload_page'))

    user = session['user']
    try:
        photos.upload_photo(
            user_id=user['sub'],
            username=user.get('cognito:username', user.get('email', 'unknown')),
            file_obj=file_obj,
            filename=file_obj.filename,
        )
        flash('Photo uploaded successfully.', 'success')
        return redirect(url_for('profile'))
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('upload_page'))


@app.route('/photos/<photo_id>/delete', methods=['POST'])
@login_required
def delete_photo(photo_id):
    """Delete a photo"""
    user_id = session['user']['sub']
    try:
        photos.delete_photo(photo_id=photo_id, user_id=user_id)
        flash('Photo deleted.', 'success')
    except photos.PhotoNotFoundError:
        flash('Photo not found.', 'warning')
    except photos.PhotoPermissionError:
        flash('You cannot delete this photo.', 'danger')

    return redirect(url_for('profile'))


@app.route('/photos/<photo_id>/privacy', methods=['POST'])
@login_required
def toggle_photo_privacy(photo_id):
    """Toggle photo privacy"""
    user_id = session['user']['sub']
    try:
        updated_photo = photos.toggle_privacy(photo_id=photo_id, user_id=user_id)
        if updated_photo.get('is_private'):
            flash('Photo is now private.', 'info')
        else:
            flash('Photo is now public.', 'info')
    except photos.PhotoNotFoundError:
        flash('Photo not found.', 'warning')
    except photos.PhotoPermissionError:
        flash('You cannot modify this photo.', 'danger')

    return redirect(url_for('profile'))