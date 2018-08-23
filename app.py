#!/usr/bin/env python

import base64
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
import enum
from functools import partial
import json
import logging
import os
import re
import requests
import uuid

from flask import Flask, abort, request, jsonify, render_template, redirect, flash, url_for, session
from flask_login import (
    LoginManager,
    login_user as _login_user,
    logout_user as _logout_user,
    login_required,
    current_user,
)

# from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from notifications_python_client.notifications import NotificationsAPIClient
from sqlalchemy.orm import backref
from sqlalchemy.orm.exc import NoResultFound

from errors import TrelloUnauthorized, GithubUnauthorized, HookAlreadyExists
from github import GithubClient
from trello import TrelloClient
from forms import AuthorizeTrelloForm, ChooseGithubRepoForm, ChooseTrelloBoardForm, ChooseTrelloListForm, LoginForm


logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")

app.config["NOTIFY_TEMPLATE_LOGIN_LINK"] = "aa07a6f4-0b7b-4101-9184-cc7f0ad620cc"
app.config["NOTIFY_API_KEY"] = os.environ["NOTIFY_API_KEY"]

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"].encode("utf8")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:////tmp/flask_app.db")
app.config["SQLALCHEMY_ECHO"] = False
app.config["CSRF_ENABLED"] = False
db = SQLAlchemy(app)
APP_NAME = "product-signoff"

# app.config["MAIL_SERVER"] = os.environ["MAILGUN_SMTP_SERVER"]
# app.config["MAIL_PORT"] = os.environ["MAILGUN_SMTP_PORT"]
# app.config["MAIL_USE_TLS"] = True
# app.config["MAIL_USERNAME"] = os.environ["MAILGUN_SMTP_LOGIN"]
# app.config["MAIL_PASSWORD"] = os.environ["MAILGUN_SMTP_PASSWORD"]
# app.config["MAIL_DEFAULT_SENDER"] = "test@" + os.environ["MAILGUN_DOMAIN"]

# app.config["MAIL_SERVER"] = os.environ["SPARKPOST_SMTP_HOST"]
# app.config["MAIL_PORT"] = os.environ["SPARKPOST_SMTP_PORT"]
# app.config["MAIL_USE_TLS"] = True
# app.config["MAIL_USERNAME"] = os.environ["SPARKPOST_SMTP_USERNAME"]
# app.config["MAIL_PASSWORD"] = os.environ["SPARKPOST_SMTP_PASSWORD"]
# app.config["MAIL_DEFAULT_SENDER"] = "product-signoff@" + os.environ["SPARKPOST_SANDBOX_DOMAIN"]

# mail = Mail(app)
login_manager = LoginManager(app)
login_manager.login_view = ".login"

AWAITING_PRODUCT_REVIEW = "Awaiting product signoff"
TICKET_APPROVED_BY = "Product signoff has been received"

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

SERVER_NAME = os.environ.get("SERVER_NAME", "localhost:5000")


@app.errorhandler(TrelloUnauthorized)
def trello_unauthorized_handler(error):
    flash(f"Invalid authorization with Trello: {str(error)}")
    current_user.trello_token = None
    db.session.add(current_user)
    db.session.commit()
    return redirect(url_for(".dashboard"))


@app.errorhandler(GithubUnauthorized)
def github_unauthorized_handler(error):
    flash(f"Invalid authorization with GitHub: {str(error)}")
    current_user.github_token = None
    db.session.add(current_user)
    db.session.commit()
    return redirect(url_for(".dashboard"))


if SERVER_NAME != "localhost:5000":
    url_for = partial(url_for, _external=True, _scheme="https")


def my_login_user(user):
    _login_user(user)
    session["token_guid"] = user.current_login_token_guid
    flash("Login successful", "info")


def my_logout_user():
    _logout_user()
    if "token_guid" in session:
        del session["token_guid"]


def find_trello_card_ids_in_text(text):
    urls = re.findall(r"(?:https?://)?(?:www.)?trello.com/c/\w+\b", text)
    return {os.path.basename(url) for url in urls}


class StatusEnum(enum.Enum):
    """
    Matches status options from GitHub status feature: https://developer.github.com/v3/repos/statuses/#create-a-status

    PENDING -> Trello ticket for this PR still needs product review.
    SUCCESS -> Trello ticket for this PR has been moved into 'Product accepted' column.
    """

    PENDING = "pending"
    SUCCESS = "success"


class LoginToken(db.Model):
    __tablename__ = "login_token"
    guid = db.Column(db.Text, primary_key=True)  # TODO:  should change this to a binary/native uuid type
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    payload = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(minutes=5))
    consumed_at = db.Column(db.DateTime, nullable=True)  # either by logging in or creating a second token

    @classmethod
    def create_token(cls, user):
        assert isinstance(user, User)
        tokens = cls.query.filter(cls.user_id == user.id)
        for token in tokens:
            if not token.consumed_at:
                token.consumed_at = datetime.utcnow()
                db.session.add(token)
            db.session.commit()

        token = cls()
        token.guid = str(uuid.uuid4())
        token.user = user

        fernet = Fernet(app.config["SECRET_KEY"])
        payload_data = {"user_id": user.id, "token_guid": token.guid}
        payload = base64.urlsafe_b64encode(fernet.encrypt(json.dumps(payload_data).encode("utf8"))).decode("utf8")
        token.payload = payload

        db.session.add(token)
        db.session.commit()

        return token

    @classmethod
    def login_user(cls, payload):
        my_logout_user()
        fernet = Fernet(app.config["SECRET_KEY"])
        payload_data = json.loads(fernet.decrypt(base64.urlsafe_b64decode(payload.encode("utf8"))))
        token = cls.query.get(payload_data["token_guid"])

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
                "Token expired: ",
                token,
                token.guid,
                token.payload,
                token.expires_at,
                datetime.utcnow(),
                token.created_at,
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


class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text, index=True)
    active = db.Column(db.Boolean, default=False)
    current_login_token_guid = db.Column(db.Text, db.ForeignKey(LoginToken.guid), nullable=True)
    github_state = db.Column(db.Text, nullable=True)
    github_token = db.Column(db.Text, nullable=True)
    trello_token = db.Column(db.Text, nullable=True)

    login_tokens = db.relationship(
        LoginToken, primaryjoin=id == LoginToken.user_id, lazy="joined", backref=backref("user")
    )
    current_login_token = db.relationship(
        LoginToken, primaryjoin=current_login_token_guid == LoginToken.guid, lazy="joined"
    )

    @classmethod
    def find_or_create(cls, email):
        user = cls.query.filter(cls.email == email).first()
        if not user:
            user = cls(email=email)
            db.session.add(user)
            db.session.commit()
        return user

    def is_authenticated(self):
        return self.id and self.active is True

    def is_active(self):
        return self.is_authenticated()

    def is_anonymous(self):
        return not self.is_authenticated()

    def get_id(self):
        return str(self.id)


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


class GithubRepo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.Text, index=True, nullable=False)
    hook_id = db.Column(db.Integer, index=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), index=True, nullable=False)

    user = db.relationship(User, lazy="joined", backref="github_repos")


class PullRequestStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sha = db.Column(db.Text, nullable=False)
    status = db.Column(db.Text, nullable=False)  # should be an enum
    repo_id = db.Column(db.Integer, db.ForeignKey(GithubRepo.id), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False)

    repo = db.relationship(GithubRepo, lazy="joined", backref="pull_requests")
    user = db.relationship(User, lazy="joined", backref="pull_requests")

    @classmethod
    def get_or_create(cls, id_, sha, github_repo, user):
        pull_request = cls.query.get(id_)
        if pull_request:
            logging.debug(f"Found existing pull request {pull_request}")
            pull_request.sha = sha
            return pull_request

        if not github_repo:
            return

        pull_request = cls(id=id_, sha=sha, status=StatusEnum.PENDING.value, repo_id=github_repo.id, user_id=user.id)
        logging.debug(f"Created new pull request {pull_request}")

        return pull_request


class TrelloList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Text, index=True, nullable=False)
    hook_id = db.Column(db.Text, index=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), index=True, nullable=False)

    user = db.relationship(User, lazy="joined", backref="trello_lists")

    @property
    def list_name(self):
        trello_client = get_trello_client(current_user)
        return trello_client.get_list(self.list_id)["name"]

    @property
    def board_name(self):
        trello_client = get_trello_client(current_user)
        return trello_client.get_board(trello_client.get_list(self.list_id)["idBoard"])["name"]


class TrelloCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.Text, index=True, nullable=False)
    pull_request_id = db.Column(db.Integer, db.ForeignKey(PullRequestStatus.id), index=True, nullable=False)

    pull_request = db.relationship(
        PullRequestStatus, lazy="joined", backref="trello_cards"
    )

    __table_args__ = (db.UniqueConstraint(card_id, pull_request_id, name="uix_card_id_pull_request_id"),)


# class TrelloChecklistItem(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     card_id = db.Column(db.Text, index=True, nullable=False)
#     pull_request_id = db.Column(db.Integer, db.ForeignKey(PullRequestStatus.id), index=True, nullable=False)

#     pull_request = db.relationship(PullRequestStatus, lazy="joined", backref="checklist_items")


def get_github_client(user):
    return GithubClient(client_id=GITHUB_CLIENT_ID, client_secret=GITHUB_CLIENT_SECRET, user=user)


def get_trello_client(user):
    return TrelloClient(key=TRELLO_API_KEY, user=user)


class Updater:
    def __init__(self, db, user):
        self.db = db
        self.user = user
        self.github_client = get_github_client(user)
        self.trello_client = get_trello_client(user)

    def _set_pull_request_status(self, pull_request, status):
        description = TICKET_APPROVED_BY if status == StatusEnum.SUCCESS.value else AWAITING_PRODUCT_REVIEW
        response = self.github_client.set_pull_request_status(
            repo_fullname=pull_request.repo.fullname,
            sha=pull_request.sha,
            status=status,
            description=description,
            context=APP_NAME,
        )

        if response.status_code != 201:
            logger.error(response, response.text)

    def _sync_trello_cards_for_pull_request(self, pull_request, body):
        all_trello_card_ids = find_trello_card_ids_in_text(body)
        existing_trello_card_ids = {
            card.card_id for card in TrelloCard.query.filter(TrelloCard.pull_request_id == pull_request.id).all()
        }

        # Old cards - need to remove
        for card_id in existing_trello_card_ids - all_trello_card_ids:
            old_trello_card = TrelloCard.query.filter(TrelloCard.card_id == card_id).one()
            db.session.delete(old_trello_card)

        # New cards - need to create
        for card_id in all_trello_card_ids - existing_trello_card_ids:
            new_trello_card = TrelloCard(card_id=card_id, pull_request_id=pull_request.id)
            db.session.add(new_trello_card)

    def sync_pull_request(self, id_, sha, body, github_repo):
        pull_request = PullRequestStatus.get_or_create(id_=id_, sha=sha, github_repo=github_repo, user=github_repo.user)

        self._sync_trello_cards_for_pull_request(pull_request=pull_request, body=body)

        db.session.add(pull_request)
        db.session.commit()

        signed_off_count = 0
        for trello_card in pull_request.trello_cards:
            trello_list = TrelloList.query.filter(
                TrelloList.list_id == self.trello_client.get_card_list(trello_card.card_id)["id"]
            ).first()

            if trello_list:
                signed_off_count += 1

        total_required_count = len(pull_request.trello_cards)
        if signed_off_count < total_required_count:
            self._set_pull_request_status(pull_request, StatusEnum.PENDING.value)
        else:
            self._set_pull_request_status(pull_request, StatusEnum.SUCCESS.value)

    def sync_repositories(self, chosen_repo_fullnames):
        existing_repo_fullnames = {
            repo.fullname for repo in GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
        }

        repos_to_deintegrate = GithubRepo.query.filter(
            GithubRepo.fullname.in_(existing_repo_fullnames - chosen_repo_fullnames)
        ).all()

        for repo_to_deintegrate in repos_to_deintegrate:
            self.github_client.delete_webhook(repo_to_deintegrate.fullname, repo_to_deintegrate.hook_id)
            db.session.delete(repo_to_deintegrate)
            flash(f"Product signoff checks removed from the “{repo_to_deintegrate.fullname}” repository.")

        for repo_to_integrate in chosen_repo_fullnames - existing_repo_fullnames:
            hook = self.github_client.create_webhook(
                repo_fullname=repo_to_integrate,
                callback_url=url_for(".github_callback", _external=True),
                events=["pull_request"],
                active=True,
            )
            db.session.add(GithubRepo(fullname=repo_to_integrate, hook_id=hook["id"], user_id=current_user.id))
            flash(f"Product signoff checks added for the “{repo_to_integrate}” repository.")

        db.session.commit()

    def sync_trello_card(self, trello_cards):
        for trello_card in trello_cards:
            signed_off_count = 0

            for sub_trello_card in trello_card.pull_request.trello_cards:
                trello_list = TrelloList.query.filter(
                    TrelloList.list_id == self.trello_client.get_card_list(sub_trello_card.card_id)["id"]
                ).first()

                if trello_list:
                    signed_off_count += 1

            if signed_off_count < len(trello_card.pull_request.trello_cards):
                self._set_pull_request_status(pull_request=trello_card.pull_request, status=StatusEnum.PENDING.value)
            else:
                self._set_pull_request_status(pull_request=trello_card.pull_request, status=StatusEnum.SUCCESS.value)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET" and current_user.is_authenticated:
        return redirect(url_for(".dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.find_or_create(form.email.data)
        if user.active:
            user.active = False
            db.session.add(user)
            db.session.commit()

        token = LoginToken.create_token(user)

        notifications_client = NotificationsAPIClient(app.config["NOTIFY_API_KEY"])
        notifications_client.send_email_notification(
            email_address=form.email.data,
            template_id=app.config["NOTIFY_TEMPLATE_LOGIN_LINK"],
            personalisation={"login_link": url_for(".login", payload=token.payload, _external=True)},
        )

        flash("A login link has been emailed to you. Please click it within 5 minutes.")

    return render_template("index.html", form=form)


@app.route("/login/<payload>")
def login(payload):
    user = LoginToken.login_user(payload)
    if user:
        return redirect(url_for(".dashboard"))

    return redirect(url_for(".index"))


@app.route("/dashboard")
@login_required
def dashboard():
    github_integrated, trello_integrated = current_user.github_token is not None, current_user.trello_token is not None

    if github_integrated:
        github_client = get_github_client(current_user)
        if github_client.is_token_valid() is False:
            flash("Your GitHub token may no longer be valid. Please revoke and re-authorize.", "warning")

    if trello_integrated:
        trello_client = get_trello_client(current_user)
        if trello_client.is_token_valid() is False:
            flash("Your Trello token may no longer be valid. Please revoke and re-authorize.", "warning")

    github_repos, trello_lists = [], []
    if github_integrated and trello_integrated:
        github_repos = GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
        trello_lists = TrelloList.query.filter(TrelloList.user_id == current_user.id).all()

    return render_template(
        "dashboard.html",
        github_integrated=github_integrated,
        trello_integrated=trello_integrated,
        github_repos=github_repos,
        trello_lists=trello_lists,
    )


@app.route("/github/integration", methods=["GET", "POST"])
@login_required
def integrate_github():
    if request.method == "POST":
        current_user.github_state = str(uuid.uuid4())
        db.session.add(current_user)
        db.session.commit()

        return redirect(
            GITHUB_OAUTH_URL.format(
                redirect_uri=url_for(".github_authorization_complete"),
                state=current_user.github_state,
                **GITHUB_OAUTH_SETTINGS,
            )
        )

    return render_template("integrate_github.html")


@app.route("/github/integration/callback", methods=["POST"])
def github_callback():
    if request.headers["X-GitHub-Event"] == "ping":
        return jsonify(status="OK"), 200

    payload = request.json["pull_request"]
    repo_fullname = payload["head"]["repo"]["full_name"]

    try:
        github_repo = GithubRepo.query.filter(GithubRepo.fullname == repo_fullname).one()

    except NoResultFound:
        logger.warning(f"Callback received but no repository registered in database: {repo_fullname}")
        return jsonify(status="OK"), 200

    updater = Updater(db, github_repo.user)
    updater.sync_pull_request(
        id_=payload["id"], sha=payload["head"]["sha"], body=payload["body"], github_repo=github_repo
    )

    return jsonify(status="OK"), 200


@app.route("/github/integration/complete")
@login_required
def github_authorization_complete():
    if request.args["state"] != current_user.github_state:
        flash("Invalid state from GitHub authentication. Possible man-in-the-middle attempt. Process aborted.")
        return redirect(url_for(".dashboard"))

    response = requests.get(
        GITHUB_TOKEN_URL,
        params={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": request.args["code"],
            "state": current_user.github_state,
        },
        headers={"Accept": "application/json"},
    )

    if response.status_code == 200:
        current_user.github_token = response.json()["access_token"]
        db.session.add(current_user)
        db.session.commit()
        flash("GitHub integration successful.")
        return redirect(url_for(".dashboard"))

    flash("Something went wrong with integration?" + str(response))
    return redirect(url_for(".dashboard"))


@app.route("/github/choose-repos", methods=["GET", "POST"])
@login_required
def github_choose_repos():
    github_client = get_github_client(current_user)
    repo_form = ChooseGithubRepoForm(github_client.get_repos())

    if repo_form.validate_on_submit():
        github_client = get_github_client(current_user)
        repo_choices = dict(repo_form.repo_choice.choices)  # refactor
        chosen_repo_fullnames = {repo_choices.get(repo_choice) for repo_choice in repo_form.repo_choice.data}

        updater = Updater(db, current_user)
        updater.sync_repositories(chosen_repo_fullnames)

        return redirect(url_for(".dashboard"))

    existing_repos = GithubRepo.query.filter(GithubRepo.user_id == current_user.id).all()
    repo_form.repo_choice.data = [repo.fullname for repo in existing_repos]

    return render_template("select-repo.html", repo_form=repo_form)


@app.route("/github/revoke", methods=["POST"])
@login_required
def revoke_github():
    github_client = get_github_client(current_user)
    if github_client.revoke_integration() is False:
        flash(
            (
                "Something went wrong revoking your GitHub integration. Please revoke it directly from "
                "https://github.com/settings/applications"
            ),
            "error",
        )

    current_user.github_token = None
    current_user.github_state = None
    db.session.add(current_user)
    db.session.commit()

    return redirect(url_for(".dashboard"))


@app.route("/trello/integration", methods=["HEAD"])
def integrate_trello_head():
    return jsonify(status="OK"), 200


@app.route("/trello/integration", methods=["POST"])
def trello_callback():
    data = json.loads(request.get_data(as_text=True))
    logging.debug("Trello callback data: " + request.get_data(as_text=True))
    if data.get("action", {}).get("type") == "updateCard":
        trello_cards = TrelloCard.query.filter(TrelloCard.card_id == data["action"]["data"]["card"]["shortLink"]).all()
        if trello_cards:
            updater = Updater(db, trello_cards[0].pull_request.user)
            updater.sync_trello_card(trello_cards)

    return jsonify(status="OK"), 200


@app.route("/trello/integration", methods=["GET"])
@login_required
def integrate_trello():
    authorize_form = AuthorizeTrelloForm()
    return render_template("integrate_trello.html", authorize_form=authorize_form)


@app.route("/trello/integration/authorize", methods=["POST"])
@login_required
def authorize_trello():
    if current_user.trello_token:
        abort(400, "Already have an integration token for Trello")

    personalized_authorize_url = (
        "{authorize_url}?expiration={expiration}&scope={scope}&name={name}&response_type=token&key={key}"
    ).format(authorize_url=TRELLO_AUTHORIZE_URL, **TRELLO_TOKEN_SETTINGS)
    return redirect(personalized_authorize_url)


@app.route("/trello/integration/complete", methods=["POST"])
@login_required
def authorize_trello_complete():
    form = AuthorizeTrelloForm()

    if form.validate_on_submit():
        if current_user.trello_token:
            abort(400, "Already have an integration token for Trello")

        current_user.trello_token = form.trello_integration.data
        db.session.add(current_user)
        db.session.commit()

        flash("Authorization complete.", "info")
        return redirect(url_for(".dashboard"))

    flash("Form submit failed", "error")
    return redirect(url_for(".index"))


@app.route("/trello/revoke", methods=["POST"])
@login_required
def revoke_trello():
    trello_client = get_trello_client(current_user)
    if trello_client.revoke_integration() is False:
        flash(
            "Something went wrong revoking your Trello integration. Please do it directly from your Trello account.",
            "error",
        )

    current_user.trello_token = None
    db.session.add(current_user)
    db.session.commit()

    return redirect(url_for(".dashboard"))


@app.route("/trello/choose-board", methods=["GET", "POST"])
@login_required
def trello_choose_board():
    trello_client = get_trello_client(current_user)
    board_form = ChooseTrelloBoardForm(trello_client.get_boards())

    if board_form.validate_on_submit():
        return redirect(url_for(".trello_choose_list", board_id=board_form.board_choice.data))

    return render_template("select-board.html", board_form=board_form)


@app.route("/signoff/choose-list", methods=["GET", "POST"])
@login_required
def trello_choose_list():
    if "board_id" not in request.args:
        flash("Please select a Trello board.")
        return redirect(".trello_choose_board")

    trello_client = get_trello_client(current_user)

    list_form = ChooseTrelloListForm(trello_client.get_lists(board_id=request.args["board_id"]))

    if list_form.validate_on_submit():
        try:
            trello_hook = trello_client.create_webhook(
                object_id=list_form.list_choice.data, callback_url=f"{url_for('.trello_callback', _external=True)}"
            )

        except HookAlreadyExists:
            pass

        else:
            trello_list = TrelloList(
                list_id=list_form.list_choice.data, hook_id=trello_hook["id"], user_id=current_user.id
            )
            db.session.add(trello_list)
            db.session.commit()

        list_choices = dict(list_form.list_choice.choices)  # refactor

        flash(
            (
                f"Product signoff will be updated on GitHub when tickets move into the "
                f"“{list_choices.get(list_form.list_choice.data)}” your product signoff integration."
            ),
            "info",
        )
        return redirect(url_for(".dashboard"))

    return render_template("select-list.html", list_form=list_form)


if __name__ == "__main__":
    db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
