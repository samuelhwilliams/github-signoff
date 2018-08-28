from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy.orm import backref

from app import db
from app.constants import StatusEnum


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
    email = db.Column(db.Text, nullable=False, index=True)

    # Whether the user's account is active. True on login, False on logout. Used for session invalidation.
    active = db.Column(db.Boolean, default=False, nullable=False, index=False)

    # Whether the user wants their connected repos to attach pull requests to checklists on Trello cards.
    # Probably wants moving off the user table?
    checklist_feature_enabled = db.Column(db.Boolean, default=False, nullable=False)

    # MATERIALIZE RELATIONSHIPS
    login_tokens = db.relationship(
        LoginToken, primaryjoin=id == LoginToken.user_id, lazy="joined", backref="user", cascade="all, delete-orphan"
    )

    @classmethod
    def find_or_create(cls, email):
        user = cls.query.filter(cls.email == email).one_or_none()
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


class GithubIntegration(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey(User.id, name="fk_github_integration_user_id"), primary_key=True)

    # The intermediate oauth2 state used to securely generate the oauth_token.
    oauth_state = db.Column(db.Text, nullable=False)

    # The user's oauth token to interact with the GitHub API.
    oauth_token = db.Column(db.Text, nullable=True)
    
    # MATERIALIZE RELATIONSHIPS
    user = db.relationship(
        User, lazy="joined", backref=backref("github_integration", cascade="all, delete-orphan", uselist=False)
    )


class TrelloIntegration(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey(User.id, name="fk_trello_integration_user_id"), primary_key=True)

    # The user's oauth token to interact with the Trello API.
    oauth_token = db.Column(db.Text, nullable=False)
    
    # MATERIALIZE RELATIONSHIPS
    trello_integration = db.relationship(
        User, lazy="joined", backref=backref("trello_integration", cascade="all, delete-orphan", uselist=False)
    )


class GithubRepo(db.Model):
    __tablename__ = "github_repo"

    # Non-sequential PK matching GitHub's internal ID for the repository.
    id = db.Column(db.Integer, primary_key=True)

    # Fullname of the repository as per GitHub. Generally of the form: `<organisation>/<repository-title>`
    fullname = db.Column(db.Text, index=True, unique=True, nullable=False)

    # Records the GitHub ID associated with the hook we create.
    hook_id = db.Column(db.Text, unique=False, nullable=True)

    # Added to the callback URL to uniquely identify which integration (i.e. user) payloads belong to.
    hook_unique_slug = db.Column(db.Text, unique=True, nullable=True)

    # Used to validate that the payload is coming from GitHub (or at least, an admin of the repo)
    hook_secret = db.Column(db.Text, index=True, unique=False, nullable=True)

    # DECLARE RELATIONSHIPS
    # Which github integration connected the repository (i.e. which user). Gives references to oauth token and hook id.
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey(GithubIntegration.user_id, name="fk_github_repo_github_integration_user_id"),
        index=False,
        nullable=False,
    )

    # MATERIALIZE RELATIONSHIPS
    integration = db.relationship(
        GithubIntegration, lazy="joined", backref=backref("github_repos", cascade="all, delete-orphan")
    )

    @classmethod
    def from_json(cls, data):
        github_repo = cls.query.get(data["id"])
        if not github_repo:
            github_repo = cls()
            github_repo.hydrate(data=data)

        return github_repo

    def hydrate(self, github_client=None, data=None):
        """Pulls in the latest variable data from GitHub's API, or restores from existing GitHub API json data"""
        if not github_client and not data:
            raise ValueError("Must provide either a GitHub client or an existing json data blob")

        if not data:
            data = github_client.get_repo(self.id, as_json=True)

        self.id = data["id"]
        self.fullname = data["full_name"]
        current_app.logger.debug(f"Created new repo {self}")

        return self


class PullRequest(db.Model):
    __tablename__ = "pull_request"

    # Sequential PK
    id = db.Column(db.Integer, primary_key=True)

    # The number of the pull request (sequential per repository - determined by GitHub)
    number = db.Column(db.Integer, nullable=False)

    # DECLARE RELATIONSHIPS
    repo_id = db.Column(
        db.Integer, db.ForeignKey(GithubRepo.id, name="fk_pull_request_github_repo_id"), nullable=False
    )

    # MATERIALIZE RELATIONSHIPS
    repo = db.relationship(GithubRepo, lazy="joined", backref=backref("pull_requests", cascade="all, delete-orphan"))

    @classmethod
    def from_json(cls, data):
        pull_request = cls.query.get(data["id"])
        if not pull_request:
            pull_request = cls()

        pull_request.hydrate(data=data)

        return pull_request

    def hydrate(self, github_client=None, data=None):
        """Pulls in the latest variable data from GitHub's API, or restores from existing GitHub API json data"""
        if not github_client and not data:
            raise ValueError("Must provide either a GitHub client or an existing json data blob")

        if not data:
            data = github_client.get_pull_request(repo_id=self.repo_id, pull_request_id=self.number, as_json=True)

        # Core model fields
        self.id = data["id"]
        self.number = data["number"]
        self.repo_id = data["head"]["repo"]["id"]

        # Additional fields hydrated from the GitHub API - not persisted or available otherwise.
        self.html_url = data["html_url"]
        self.statuses_url = data["statuses_url"]
        self.body = data["body"]
        self.state = data["state"]  # TODO: fix this conflcit with enum

        current_app.logger.debug(f"Created new pull request {self}")

        return self


class TrelloBoard:
    """
    Converts a JSON data blob from the Trello API in a Python object representing a Trello Board.
    """

    @classmethod
    def from_json(cls, data):
        """Create a TrelloBoard instance from Trello API data."""
        trello_board = cls()
        trello_board.hydrate(data=data)
        return trello_board

    def hydrate(self, trello_client=None, data=None):
        """Populate the object either from an existing Trello JSON data blob or by fetching one"""
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_board(self.board_id, as_json=True)

        # Additional fields hydrated from the Trello API - not persisted or available otherwise.
        self.board_id = data["id"]
        self.name = data["name"]
        
        if "lists" in data:
            self.lists = [TrelloList.from_json(list_data) for list_data in data["lists"]]

        return self


class TrelloList(db.Model):
    __tablename__ = "trello_list"

    # Non-sequential text-based PK matching Trello's internal ID for the list.
    # Performance issues at scale?
    id = db.Column(db.Text, primary_key=True)

    # Records the Trello ID associated with the hook we create.
    hook_id = db.Column(db.Text, nullable=True)

    # DECLARE RELATIONSHIPS
    integration_id = db.Column(
        db.Integer,
        db.ForeignKey(TrelloIntegration.user_id, name="fk_trello_list_trello_integration_user_id"),
        index=False,
        nullable=False,
    )

    # MATERIALIZE RELATIONSHIPS
    integration = db.relationship(
        TrelloIntegration, lazy="joined", backref=backref("trello_lists", cascade="all, delete-orphan")
    )

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

        # Core model fields
        self.id = data["id"]
        
        # Additional fields hydrated from the Trello API - not persisted or available otherwise.
        self.name = data["name"]
        self.board_id = data["idBoard"]

        return self


class PullRequestTrelloCard(db.Model):
    """Join table for many-to-many relationship of PullRequest and TrelloCard"""
    __tablename__ = "pull_request_trello_card"
    card_id = db.Column(
        db.Text, db.ForeignKey("trello_card.id", name="fk_pull_request_trello_card_card_id"), primary_key=True
    )
    pull_request_id = db.Column(
        db.Integer,
        db.ForeignKey(PullRequest.id, name="fk_pull_request_trello_card_pull_request_id"),
        primary_key=True,
    )


class TrelloCard(db.Model):
    __tablename__ = "trello_card"
    
    # Non-sequential text-based PK matching Trello's internal ID for the card.
    id = db.Column(db.Text, primary_key=True)

    # MATERIALIZE RELATIONSHIPS
    pull_requests = db.relationship(
        PullRequest,
        secondary="pull_request_trello_card",
        lazy="joined",
        backref=backref("trello_cards", cascade="all"),
        uselist=True,
    )

    @classmethod
    def from_json(cls, data):
        trello_card = cls.query.filter(cls.id == data["shortLink"]).one_or_none()
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
    
    # Non-sequential text-based PK matching Trello's internal ID for the checklist.
    id = db.Column(db.Text, primary_key=True)
    
    # DECLARE RELATIONSHIPS
    card_id = db.Column(
        db.Text, db.ForeignKey(TrelloCard.id, name="fk_trello_checklist_trello_card_id"), unique=True, nullable=False
    )

    # MATERIALIZE RELATIONSHIPS
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
        self.checkitems = [TrelloCheckitem.from_json(item_data) for item_data in data.get("checkItems", [])]

        return self


class TrelloCheckitem(db.Model):
    __tablename__ = "trello_checkitem"
    
    # Non-sequential text-based PK matching Trello's internal ID for the checkitem.
    id = db.Column(db.Text, primary_key=True)
    
    # DECLARE RELATIONSHIPS
    checklist_id = db.Column(
        db.Text,
        db.ForeignKey(TrelloChecklist.id, name="fk_trello_checkitem_trello_checklist_id"),
        db.UniqueConstraint(name="uix_id"),
        nullable=False,
    )
    pull_request_id = db.Column(
        db.Integer,
        db.ForeignKey(PullRequest.id, name="fk_trello_checkitem_pull_request_id"),
        nullable=False,
    )

    # MATERIALIZE RELATIONSHIPS
    checklist = db.relationship(
        TrelloChecklist, lazy="joined", backref=backref("trello_checkitems", cascade="all, delete-orphan")
    )
    pull_request = db.relationship(
        PullRequest, lazy="joined", backref=backref("trello_checkitems", cascade="all, delete-orphan")
    )

    # Each pull request may only appear on a given checklist once.
    __table_args__ = (db.UniqueConstraint(checklist_id, pull_request_id, name="uix_checklist_id_pull_request_id"),)

    @classmethod
    def from_json(cls, data):
        trello_checkitem = cls()
        trello_checkitem.hydrate(data=data)
        return trello_checkitem

    def hydrate(self, trello_client=None, data=None):
        if not trello_client and not data:
            raise ValueError("Must provide either a Trello client or an existing json data blob")

        if not data:
            data = trello_client.get_checkitem(
                checklist_id=self.checklist_id, checkitem_id=self.id, as_json=True
            )

        self.id = data["id"]
        self.checklist_id = data["idChecklist"]
        self.name = data["name"]
        self.state = data["state"]

        return self
