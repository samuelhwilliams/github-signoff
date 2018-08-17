from logging import WARNING as LOGLEVEL_WARNING, DEBUG as LOGLEVEL_DEBUG
import os
from datetime import timedelta


class Config:
    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    PORT = os.environ.get("PORT", 5000)
    DEBUG = False
    TESTING = False
    LOG_LEVEL = os.environ.get("LOG_LEVEL", LOGLEVEL_WARNING)
    DEBUG_PAYLOADS = os.environ.get("DEBUG_PAYLOADS", False)

    APP_NAME = "G&T Powerup"
    SECRET_KEY = os.environ["SECRET_KEY"].encode("utf8")
    SERVER_NAME = os.environ.get("SERVER_NAME")

    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    FEATURE_CHECKLIST_NAME = "Pull requests"

    PREFERRED_URL_SCHEME = "https"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "postgresql://localhost/product_signoff")
    SQLALCHEMY_ECHO = False
    CSRF_ENABLED = True

    MAIL_DOMAIN = os.environ["MAIL_DOMAIN"]
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", f"login@{MAIL_DOMAIN}")
    MAIL_SERVER = os.environ["SPARKPOST_SMTP_HOST"]
    MAIL_PORT = os.environ["SPARKPOST_SMTP_PORT"]
    MAIL_USERNAME = os.environ["SPARKPOST_SMTP_USERNAME"]
    MAIL_PASSWORD = os.environ["SPARKPOST_SMTP_PASSWORD"]

    TRELLO_API_KEY = os.environ["TRELLO_API_KEY"]
    TRELLO_API_SECRET = os.environ["TRELLO_API_SECRET"]
    TRELLO_AUTHORIZE_URL = "https://trello.com/1/authorize"
    TRELLO_TOKEN_SETTINGS = dict(expiration="never", scope="read,write", name="github-signoff", key=TRELLO_API_KEY)

    GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
    GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
    GITHUB_OAUTH_SETTINGS = dict(client_id=GITHUB_CLIENT_ID, scope="admin:repo_hook, repo")
    GITHUB_OAUTH_URL = (
        "https://github.com/login/oauth/authorize"
        "?client_id={client_id}"
        "&redirect_uri={redirect_uri}"
        "&scope={scope}"
        "&state={state}"
    )
    GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
    GITHUB_APPLICATION_ID = "2d19768ca3d464d67172"
    GITHUB_APPLICATION_SETTINGS_URL = f"https://github.com/settings/connections/applications/{GITHUB_APPLICATION_ID}"


class DevConfig(Config):
    FLASK_ENV = "development"
    DEBUG = True
    SQLALCHEMY_ECHO = True
    CSRF_ENABLED = False
    LOG_LEVEL = LOGLEVEL_DEBUG


class TestConfig(DevConfig):
    TESTING = True

    NOTIFY_API_KEY = "fakeKey"

    TRELLO_API_KEY = "fakeKey"
    TRELLO_API_SECRET = "fakeSecret"

    GITHUB_CLIENT_ID = "fakeId"
    GITHUB_CLIENT_SECRET = "fakeSecret"

    MAIL_DOMAIN = "fakeDomain"
    MAIL_DEFAULT_SENDER = "fakeSender"
    MAIL_SERVER = "fakeServer"
    MAIL_PORT = "fakePort"
    MAIL_USERNAME = "fakeUser"
    MAIL_PASSWORD = "fakePassword"


config_map = {"production": Config, "development": DevConfig, "test": TestConfig}
