#!/usr/bin/env python

from cryptography.fernet import Fernet
from datetime import datetime, timedelta
import enum
import json
import os
import requests
import uuid

from flask import (
    Flask,
    abort,
    request,
    jsonify,
    render_template,
    redirect,
    flash,
    url_for,
    session,
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload

from trello import TrelloClient
from forms import (
    AuthorizeTrelloForm,
    ChooseTrelloBoardForm,
    ChooseTrelloListForm,
    LoginForm,
)


app = Flask(__name__, template_folder="templates")

app.config["SECRET_KEY"] = os.environ["SECRET_KEY"].encode("utf8")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:////tmp/flask_app.db"
)
app.config["CSRF_ENABLED"] = False
db = SQLAlchemy(app)
APP_NAME = "github-signoff"

app.config["MAIL_SERVER"] = os.environ["MAILGUN_SMTP_SERVER"]
app.config["MAIL_PORT"] = os.environ["MAILGUN_SMTP_PORT"]
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ["MAILGUN_SMTP_LOGIN"]
app.config["MAIL_PASSWORD"] = os.environ["MAILGUN_SMTP_PASSWORD"]
app.config["MAIL_DEFAULT_SENDER"] = "test@" + os.environ["MAILGUN_DOMAIN"]

mail = Mail(app)
login_manager = LoginManager(app)

AWAITING_PRODUCT_REVIEW = "Awaiting product review"
TICKET_APPROVED_BY = "Product accepted by {user}"
TRELLO_AUTHORIZE_URL = "https://trello.com/1/authorize"
GITHUB_OAUTH_URL = (
    "https://github.com/login/oauth/authorize"
    "?client_id={client_id}"
    "&redirect_uri={redirect_uri}"
    "&scope={scope}"
    "&state={state}"
)
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

TRELLO_API_KEY = os.environ["TRELLO_API_KEY"]
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
SERVER_NAME = os.environ["SERVER_NAME"]


def my_login_user(user):
    login_user(user)
    session["token_id"] = user.current_token_id


def my_logout_user():
    logout_user()
    if "token_id" in session:
        del session["token_id"]


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
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    payload = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.utcnow() + timedelta(minutes=5),
    )
    consumed_at = db.Column(
        db.DateTime, nullable=True
    )  # either by logging in or creating a second token

    @classmethod
    def create_token(cls, user):
        assert isinstance(user, User)
        tokens = cls.query.filter(cls.user_id == user.id)
        for token in tokens:
            if not token.consumed_at:
                token.consumed_at = datetime.utcnow()
                db.session.add(token)
            db.session.commit()

        fernet = Fernet(app.config["SECRET_KEY"])
        payload = fernet.encrypt(json.dumps({"id": user.id}).encode("utf8"))

        token = cls()
        token.user = user
        token.payload = payload

        db.session.add(token)
        db.session.commit()

        return token

    @classmethod
    def login_user(cls, payload):
        fernet = Fernet(app.config["SECRET_KEY"])
        data = json.loads(fernet.decrypt(payload.encode("utf8")).decode("utf8"))
        token = cls.query.filter(
            cls.user_id == data["id"], cls.consumed_at == None
        ).first()

        if not token:
            flash("no token", "error")
            return None

        if token.consumed_at:
            flash("token already used", "error")
            return None

        if datetime.now() <= token.expires_at:
            flash("token expired", "error")
            return None

        token.consumed_at = datetime.now()
        token.user.active = True
        token.user.current_token = token

        db.session.add(token)
        db.session.add(token.user)
        db.session.commit()

        my_login_user(token.user)

        flash("Login successful", "info")

        return token.user


class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text, index=True)
    active = db.Column(db.Boolean, default=False)
    current_token_id = db.Column(
        db.Integer, db.ForeignKey("login_token.id"), nullable=True
    )

    login_tokens = db.relationship(
        LoginToken, primaryjoin=id == LoginToken.user_id, lazy="joined", backref="user"
    )
    current_token = db.relationship(
        LoginToken, primaryjoin=current_token_id == LoginToken.id, lazy="joined"
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

    elif "token_id" not in session:
        return None

    elif user.current_token_id != session["token_id"]:
        flash("You have been logged of the session.")
        del session["token_id"]
        return None

    return user


class Integration(db.Model):
    guid = db.Column(db.Text, primary_key=True)
    github_oauth_state = db.Column(db.Text, index=True, nullable=False)
    github_token = db.Column(db.Text, nullable=True)
    repository_id = db.Column(db.BigInteger, unique=True, nullable=True)
    trello_token = db.Column(db.Text, unique=True, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False)
    
    user = db.relationship(User, lazy="joined", backref="integrations")


class IntegratedTrelloList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    integration_guid = db.Column(db.Text, db.ForeignKey(Integration.guid))
    trello_list_id = db.Column(db.BigInteger, unique=True, index=True)
    
    integration = db.relationship(Integration, lazy="joined", backref="trello_lists")


class PullRequestStatus(db.Model):
    guid = db.Column(db.Text, primary_key=True)
    head_sha = db.Column(db.Text, index=True, nullable=False)
    repository_id = db.Column(
        db.BigInteger,
        db.ForeignKey(Integration.repository_id),
        index=True,
        nullable=False,
    )
    organisation = db.Column(db.Text)
    repository = db.Column(db.Text)
    branch = db.Column(db.Text, index=True, nullable=False)
    status = db.Column(db.Text, nullable=False)  # should be an enum
    url = db.Column(db.Text, nullable=False)
    integration_guid = db.Column(db.Text, db.ForeignKey(Integration.guid), nullable=False)
    trello_list_id = db.Column(db.Text, index=True, nullable=True)

    integration = db.relationship(Integration, primaryjoin=integration_guid == Integration.guid, lazy="joined", backref="pull_requests")

    @classmethod
    def create_from_github(cls, data):
        if "pull_request" in data:
            data = data["pull_request"]

            pr = PullRequestStatus.get(data["id"]).first()

            if not pr:
                pr = PullRequestStatus(
                    id=data["id"],
                    head_sha=data["head"]["sha"],
                    branch=data["head"]["ref"],
                    status=StatusEnum.PENDING.value,
                    url=data["head"]["repo"]["statuses_url"].format(
                        sha=data["head"]["sha"]
                    ),
                )

            response = pr.set_github_status(
                state=StatusEnum.PENDING.value,
                description=AWAITING_PRODUCT_REVIEW,
                context=APP_NAME,
            )
            if response.status_code == 201:
                db.session.add(pr)
                db.session.commit()

    def set_github_status(self, state, description, context):
        return requests.post(
            self.url,
            json={"state": state, "description": description, "context": context},
            auth=("samuelhwilliams", os.environ["GITHUB_ACCESS_TOKEN"]),
        )


@app.route("/", methods=["GET", "POST"])
def index():
    form = LoginForm()

    if form.validate_on_submit():
        user = User.find_or_create(form.email.data)
        if user.active:
            user.active = False
            db.session.add(user)
            db.session.commit()

        token = LoginToken.create_token(user)
        body = render_template("email_login_link.html", payload=token.payload)
        msg = Message(
            "Login to Github-Trello-Signoff",
            sender=app.config["MAIL_DEFAULT_SENDER"],
            recipients=[form.email.data],
            html=body,
        )
        print(url_for(".login", payload=token.payload, _external=True))
        # mail.send(msg)

        flash("A login link has been emailed to you. Please click it within 5 minutes.")

    return render_template("index.html", form=form)


@app.route("/login/<payload>")
def login(payload):
    form = LoginForm()
    user = LoginToken.login_user(payload)
    return redirect(url_for(".dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    integrations = Integration.query.filter(Integration.user_id == current_user.id).all()
    return render_template("dashboard.html", integrations=integrations)


@app.route("/integration/start-github")
@login_required
def integrate_github():
    return render_template("integrate_github.html")


@app.route('/integration/authorize-github', methods=["POST"])
@login_required
def authorize_github():
    integration = Integration(
        guid=str(uuid.uuid4()),
        github_oauth_state=str(uuid.uuid4()),
        user_id=current_user.id,
    )
    db.session.add(integration)
    db.session.commit()
    session["integration"] = integration.guid
    
    return redirect(
        GITHUB_OAUTH_URL.format(
            client_id=GITHUB_CLIENT_ID,
            redirect_uri="https://" + os.environ["SERVER_NAME"] + url_for(".github_authorization_complete"),
            scope="repo:status",
            state=integration.github_oauth_state,
        )
    )
    


@app.route("/github/callback", methods=["GET", "POST"])
def github_events():
    # trello_card_urls = PullRequestStatus.find_trello_card_urls(request.json)
    print(request)
    if request.json:
        PullRequestStatus.create_from_github(request.json)

    return jsonify(status="OK"), 200


@app.route("/github/callback/complete")
@login_required
def github_authorization_complete():
    integration = Integration.query.filter(
        Integration.guid == session["integration"]
    ).one()

    response = requests.get(
        GITHUB_TOKEN_URL,
        params={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": request.args["code"],
            "state": integration.github_oauth_state,
        },
        headers={"Accept": "application/json"},
    )

    if response.status_code == 200:
        integration.github_token = response.json()["access_token"]
        db.session.add(integration)
        db.session.commit()
        flash("GitHub integration successful.")
        return redirect(url_for(".integrate_trello"))

    flash("Something went wrong with integration?" + str(response))
    return redirect(url_for(".dashboard"))


@app.route("/integration/start-trello")
def integrate_trello():
    authorize_form = AuthorizeTrelloForm()
    return render_template("integrate_trello.html", authorize_form=authorize_form)


@app.route("/trello/authorize", methods=["POST"])
def authorize_trello():
    personalized_authorize_url = "{authorize_url}?expiration={expiration}&scope={scope}&name={name}&response_type=token&key={key}".format(
        authorize_url=TRELLO_AUTHORIZE_URL,
        expiration="1day",
        scope="read,write",
        name="github-signoff",
        key=os.environ["TRELLO_API_KEY"],
    )
    return redirect(personalized_authorize_url)


@app.route("/trello/authorize/finish", methods=["POST"])
@login_required
def authorize_trello_finish():
    form = AuthorizeTrelloForm()

    if form.validate_on_submit():
        integration = Integration.query.filter(Integration.user_id == current_user.id).one()
        integration.trello_token = form.trello_auth_key.data
        db.session.add(integration)
        db.session.commit()
        flash("Authorization complete.", "info")
        return redirect(url_for(".choose_trello_board")), 200

    flash("Form submit failed", "error")
    return redirect(url_for(".index")), 400


@app.route("/trello/choose-board")
@login_required
def choose_trello_board():
    integration = Integration.query.filter(Integration.user_id == current_user.id).one()
    trello_client = TrelloClient(TRELLO_API_KEY, integration.trello_token)

    board_form = ChooseTrelloBoardForm(trello_client.get_boards())

    return render_template("trello-select-board.html", board_form=board_form)


@app.route("/trello/choose-list", methods=["POST"])
@login_required
def choose_trello_list():
    integration = Integration.query.filter(Integration.user_id == current_user.id).one()
    trello_client = TrelloClient(TRELLO_API_KEY, integration.trello_token)
    
    board_form = ChooseTrelloBoardForm()

    list_form = ChooseTrelloListForm(
        trello_client.get_lists(board_id=board_form.board_choice.data)
    )

    return render_template("trello-select-list.html", list_form=list_form)


@app.route("/trello/create-webhook", methods=["POST"])
@login_required
def create_trello_webhook():
    integration = Integration.query.filter(Integration.user_id == current_user.id).one()
    trello_client = TrelloClient(TRELLO_API_KEY, integration.trello_token)

    list_form = ChooseTrelloListForm()

    trello_client.create_webhook(
        object_id=list_form.list_choice.data,
        callback_url=f"{SERVER_NAME}{url_for('trello_callback', integration_guid=integration.guid)}",
    )
    
    integrated_trello_list = IntegratedTrelloList(
        integration_guid=integration.guid,
        trello_list_id=list_form.list_choice.data,
    )
    
    db.session.add(integrated_trello_list)
    db.session.commit()

    flash("You have successfully integrated with Trello", "info")
    return redirect(url_for(".index")), 201


@app.route("/trello/callback", methods=["HEAD", "POST"])
@login_required
def trello_callback():
    if request.method == "POST":
        data = json.loads(request.get_data(as_text=True))
        if data.get("action", {}).get("type") == "updateCard":
            integrated_trello_list = IntegratedTrelloList.query.filter(
                IntegratedTrelloList.trello_list_id
                == data["action"]["data"]["listAfter"]["id"]
            ).one()
            
            print(integrated_trello_list.integration.pull_requests)
            
            trello_client = TrelloClient(TRELLO_API_KEY, integrated_trello_list.integration.trello_token)

            if pull_requests:
                for pull_request in pull_requests:
                    pull_requests.set_github_status(
                        state=StatusEnum.SUCCESS.value,
                        description=TICKET_APPROVED_BY,
                        context=APP_NAME,
                    )

    return jsonify(status="OK"), 200


if __name__ == "__main__":
    db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
