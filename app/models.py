from datetime import datetime, timedelta
import logging

from sqlalchemy.orm import backref

from app import db
from app.constants import StatusEnum


logger = logging.getLogger(__name__)


class LoginToken(db.Model):
    __tablename__ = "login_token"
    guid = db.Column(db.Text, primary_key=True)  # TODO:  should change this to a binary/native uuid type
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", name="fk_login_token_user_id"), index=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(minutes=5))
    consumed_at = db.Column(db.DateTime, nullable=True)  # either by logging in or creating a second token


class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text, index=True)
    active = db.Column(db.Boolean, default=False)
    github_state = db.Column(db.Text, nullable=True)
    github_token = db.Column(db.Text, nullable=True)
    trello_token = db.Column(db.Text, nullable=True)

    checklist_feature_enabled = db.Column(db.Boolean, default=False, nullable=False)

    login_tokens = db.relationship(
        LoginToken, primaryjoin=id == LoginToken.user_id, lazy="joined", backref="user", cascade="all, delete-orphan"
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


class GithubRepo(db.Model):
    __tablename__ = "github_repo"
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.Text, index=True, nullable=False)
    hook_id = db.Column(db.Integer, index=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id, name="fk_github_repo_user_id"), index=True, nullable=False)

    user = db.relationship(User, lazy="joined", backref=backref("github_repos", cascade="all, delete-orphan"))

    @classmethod
    def from_json(cls, user, data):
        github_repo = cls.query.get(data["id"])
        if not github_repo:
            github_repo = cls()
            github_repo.hydrate(data=data)
            github_repo.user_id = user.id

        elif github_repo.user_id != user.id:
            raise ValueError("Mismatch for repo owner in github callback vs database")

        return github_repo

    def hydrate(self, github_client=None, data=None):
        """Pulls in the latest variable data from GitHub's API, or restores from existing GitHub API json data"""
        if not github_client and not data:
            raise ValueError("Must provide either a GitHub client or an existing json data blob")

        if not data:
            data = github_client.get_repo(self.id, as_json=True)

        self.id = data["id"]
        self.fullname = data["full_name"]
        logger.debug(f"Created new repo {self}")

        return self


class PullRequestStatus(db.Model):
    __tablename__ = "pull_request_status"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False)
    sha = db.Column(db.Text, nullable=False)
    status = db.Column(db.Text, nullable=False)  # should be an enum
    repo_id = db.Column(
        db.Integer, db.ForeignKey(GithubRepo.id, name="fk_pull_request_status_github_repo_id"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey(User.id, name="fk_pull_request_status_user_id"), nullable=False)

    repo = db.relationship(GithubRepo, lazy="joined", backref=backref("pull_requests", cascade="all, delete-orphan"))
    user = db.relationship(User, lazy="joined", backref=backref("pull_requests", cascade="all, delete-orphan"))

    @classmethod
    def from_json(cls, user, data):
        pull_request = cls.query.get(data["id"])
        if not pull_request:
            pull_request = cls()

        elif pull_request.user_id != user.id:
            raise ValueError("Mismatch for pull request owner in github callback vs database")

        pull_request.hydrate(data=data)
        pull_request.user_id = user.id

        return pull_request

    def hydrate(self, github_client=None, data=None):
        """Pulls in the latest variable data from GitHub's API, or restores from existing GitHub API json data"""
        if not github_client and not data:
            raise ValueError("Must provide either a GitHub client or an existing json data blob")

        if not data:
            data = github_client.get_pull_request(self.id, as_json=True)

        self.id = data["id"]
        self.number = data["number"]
        self.sha = data["head"]["sha"]
        self.status = StatusEnum.PENDING.value
        self.pr_status = data["state"]  # TODO: fix this conflcit with enum
        self.repo_id = data["head"]["repo"]["id"]
        self.body = data["body"]
        self.url = data["html_url"]
        logger.debug(f"Created new pull request {self}")

        return self


class TrelloBoard:
    @classmethod
    def from_json(cls, data):
        trello_board = cls()
        trello_board.hydrate(data=data)
        return trello_board

    def hydrate(self, trello_client=None, data=None):
        """Pulls in the latest variable data from Trello's API, or restores from existing Trello API json data"""
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_board(self.board_id, as_json=True)

        self.board_id = data["id"]
        self.name = data["name"]

        return self


class TrelloList(db.Model):
    __tablename__ = "trello_list"
    id = db.Column(db.Text, primary_key=True)
    hook_id = db.Column(db.Text, index=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id, name="fk_trello_list_user_id"), index=True, nullable=False)

    user = db.relationship(User, lazy="joined", backref=backref("trello_lists", cascade="all, delete-orphan"))

    @classmethod
    def from_json(cls, data):
        trello_list = cls()
        trello_list.hydrate(data=data)
        return trello_list

    def hydrate(self, trello_client=None, data=None):
        """Pulls in the latest variable data from Trello's API, or restores from existing Trello API json data"""
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_list(self.id, as_json=True)

        self.id = data["id"]
        self.name = data["name"]
        self.board_id = data["idBoard"]

        return self


class PullRequestTrelloCard(db.Model):
    __tablename__ = "pull_request_trello_card"
    card_id = db.Column(
        db.Text, db.ForeignKey("trello_card.id", name="fk_pull_request_trello_card_card_id"), primary_key=True
    )
    pull_request_id = db.Column(
        db.Integer,
        db.ForeignKey(PullRequestStatus.id, name="fk_pull_request_trello_card_pull_request_id"),
        primary_key=True,
    )


class TrelloCard(db.Model):
    __tablename__ = "trello_card"
    id = db.Column(db.Text, primary_key=True)

    pull_requests = db.relationship(
        PullRequestStatus,
        secondary="pull_request_trello_card",
        lazy="joined",
        backref=backref("trello_cards", cascade="all"),
        uselist=True,
    )

    @classmethod
    def from_json(cls, data):
        trello_card = cls.query.filter(cls.id == data["shortLink"]).first()
        if not trello_card:
            trello_card = cls()

        trello_card.hydrate(data=data)

        return trello_card

    def hydrate(self, trello_client=None, data=None):
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_card(self.id, as_json=True)

        self.id = data["shortLink"]
        self.real_id = data["id"]

        if "list" in data:
            self.list = TrelloList.from_json(data["list"])

        if "board" in data:
            self.board = TrelloBoard.from_json(data["board"])

        return self


class TrelloChecklist(db.Model):
    __tablename__ = "trello_checklist"
    id = db.Column(db.Text, primary_key=True)
    card_id = db.Column(
        db.Text, db.ForeignKey(TrelloCard.id, name="fk_trello_checklist_trello_card_id"), unique=True, nullable=False
    )

    card = db.relationship(
        TrelloCard, lazy="joined", backref=backref("trello_checklist", uselist=False, cascade="all, delete-orphan")
    )

    @classmethod
    def from_json(cls, data):
        trello_checklist = cls()
        trello_checklist.hydrate(data=data)
        return trello_checklist

    def hydrate(self, trello_client=None, data=None):
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_checklist(self.id, as_json=True)

        self.id = data["id"]
        self.name = data["name"]
        self.checklist_items = [TrelloChecklistItem.from_json(item_data) for item_data in data.get("checkItems", [])]

        return self


class TrelloChecklistItem(db.Model):
    __tablename__ = "trello_checklist_item"
    id = db.Column(db.Text, primary_key=True)
    checklist_id = db.Column(
        db.Text,
        db.ForeignKey(TrelloChecklist.id, name="fk_trello_checklist_item_trello_checklist_id"),
        db.UniqueConstraint(name="uix_id"),
        nullable=False,
    )
    pull_request_id = db.Column(
        db.Integer,
        db.ForeignKey(PullRequestStatus.id, name="fk_trello_checklist_item_pull_request_status_id"),
        nullable=False,
    )

    checklist = db.relationship(
        TrelloChecklist, lazy="joined", backref=backref("trello_checklist_items", cascade="all, delete-orphan")
    )
    pull_request = db.relationship(
        PullRequestStatus, lazy="joined", backref=backref("trello_checklist_items", cascade="all, delete-orphan")
    )

    __table_args__ = (db.UniqueConstraint(checklist_id, pull_request_id, name="uix_checklist_id_pull_request_id"),)

    @classmethod
    def from_json(cls, data):
        trello_checklist_item = cls()
        trello_checklist_item.hydrate(data=data)
        return trello_checklist_item

    def hydrate(self, trello_client=None, data=None):
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_checklist_item(
                checklist_id=self.checklist_id, checklist_item_id=self.id, as_json=True
            )

        self.id = data["id"]
        self.checklist_id = data["idChecklist"]
        self.name = data["name"]
        self.state = data["state"]

        return self
