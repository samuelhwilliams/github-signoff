import os
from datetime import timedelta


class Config:
    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    PORT = os.environ.get("PORT", 5000)
    DEBUG = False
    TESTING = False

    SECRET_KEY = os.environ["SECRET_KEY"].encode("utf8")
    SERVER_NAME = os.environ.get("SERVER_NAME", "localhost:5000")

    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
    PREFERRED_URL_SCHEME = "https"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:////tmp/flask_app.db")
    SQLALCHEMY_ECHO = False
    CSRF_ENABLED = True

    NOTIFY_TEMPLATE_LOGIN_LINK = "aa07a6f4-0b7b-4101-9184-cc7f0ad620cc"
    NOTIFY_API_KEY = os.environ["NOTIFY_API_KEY"]

    TRELLO_API_KEY = os.environ["TRELLO_API_KEY"]
    TRELLO_API_SECRET = os.environ["TRELLO_API_SECRET"]
    TRELLO_AUTHORIZE_URL = "https://trello.com/1/authorize"
    TRELLO_TOKEN_SETTINGS = dict(expiration="1hour", scope="read,write", name="github-signoff", key=TRELLO_API_KEY)

    GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
    GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
    GITHUB_OAUTH_SETTINGS = dict(client_id=GITHUB_CLIENT_ID, scope="admin:repo_hook, repo:status")
    GITHUB_OAUTH_URL = (
        "https://github.com/login/oauth/authorize"
        "?client_id={client_id}"
        "&redirect_uri={redirect_uri}"
        "&scope={scope}"
        "&state={state}"
    )
    GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"


class DevConfig(Config):
    FLASK_ENV = "development"
    DEBUG = True
    SQLALCHEMY_ECHO = True
    CSRF_ENABLED = False


class TestConfig(DevConfig):
    TESTING = True

    NOTIFY_API_KEY = "fakeKey"

    TRELLO_API_KEY = "fakeKey"
    TRELLO_API_SECRET = "fakeSecret"

    GITHUB_CLIENT_ID = "fakeId"
    GITHUB_CLIENT_SECRET = "fakeSecret"


config_map = {"production": Config, "development": DevConfig, "test": TestConfig}
