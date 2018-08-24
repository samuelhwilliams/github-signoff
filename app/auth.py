import base64
from datetime import datetime
import json
import logging
import uuid

from cryptography.fernet import Fernet
from flask import flash, session
from flask_login import login_user as _login_user, logout_user as _logout_user

from app import login_manager
from app.models import User, LoginToken


logger = logging.getLogger(__name__)


def my_login_user(user):
    _login_user(user)
    session["token_guid"] = user.current_login_token_guid
    flash("Login successful", "info")


def my_logout_user():
    _logout_user()
    if "token_guid" in session:
        del session["token_guid"]


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(user_id)

    if not user:
        return None

    elif "token_guid" not in session:
        return None

    elif user.current_login_token_guid != session["token_guid"]:
        flash("You have been logged of the session.")
        del session["token_guid"]
        return None

    return user


def new_login_token_and_payload(app, db, user):
    assert isinstance(user, User)
    tokens = LoginToken.query.filter(LoginToken.user_id == user.id)
    for token in tokens:
        if not token.consumed_at:
            token.consumed_at = datetime.utcnow()
            db.session.add(token)
            db.session.commit()

    token = LoginToken()
    token.guid = str(uuid.uuid4())
    token.user = user

    fernet = Fernet(app.config["SECRET_KEY"])
    payload_data = {"user_id": user.id, "token_guid": token.guid}
    payload = base64.urlsafe_b64encode(fernet.encrypt(json.dumps(payload_data).encode("utf8"))).decode("utf8")

    return token, payload


def login_user(app, db, payload):
    my_logout_user()
    fernet = Fernet(app.config["SECRET_KEY"])
    payload_data = json.loads(fernet.decrypt(base64.urlsafe_b64decode(payload.encode("utf8"))))
    token = LoginToken.query.get(payload_data["token_guid"])

    if not token:
        flash("No token found", "error")

    elif token.user.id != payload_data["user_id"]:
        flash("Invalid token data", "error")
        logger.warn("Invalid token data: ", token, token.guid, token.user.id, payload_data["user_id"])

    elif token.consumed_at:
        flash("Token already used", "error")
        logger.warn("Token already used: ", token, token.guid, token.payload, token.consumed_at)

    elif datetime.utcnow() >= token.expires_at:
        flash("Token expired", "error")
        logger.warn(
            "Token expired: ", token, token.guid, token.payload, token.expires_at, datetime.utcnow(), token.created_at
        )

    else:
        token.consumed_at = datetime.utcnow()
        token.user.active = True
        # token.user.current_login_token = token

        db.session.add(token)
        db.session.add(token.user)
        db.session.commit()

        my_login_user(token.user)

        return token.user

    return None
