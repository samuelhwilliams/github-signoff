from datetime import datetime, timedelta

from sqlalchemy.orm import backref

from app import db


class LoginToken(db.Model):
    __tablename__ = "login_token"
    guid = db.Column(db.Text, primary_key=True)  # TODO:  should change this to a binary/native uuid type
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(minutes=5))
    consumed_at = db.Column(db.DateTime, nullable=True)  # either by logging in or creating a second token


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

    pull_request = db.relationship(PullRequestStatus, lazy="joined", backref="trello_cards")

    __table_args__ = (db.UniqueConstraint(card_id, pull_request_id, name="uix_card_id_pull_request_id"),)


# class TrelloChecklistItem(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     card_id = db.Column(db.Text, index=True, nullable=False)
#     pull_request_id = db.Column(db.Integer, db.ForeignKey(PullRequestStatus.id), index=True, nullable=False)

#     pull_request = db.relationship(PullRequestStatus, lazy="joined", backref="checklist_items")
