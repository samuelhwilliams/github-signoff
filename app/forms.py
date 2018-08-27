from flask_wtf import FlaskForm
from wtforms import StringField, HiddenField, RadioField
from wtforms.validators import DataRequired, Email

from app.design_system_fields import DSCheckboxField, DSRadioField


class LoginForm(FlaskForm):
    email = StringField(label="Email address", validators=[Email()])


class LoginWithPayloadForm(FlaskForm):
    # Used only as a hook into FlaskForm's CSRF protection
    pass


class DeleteAccountForm(FlaskForm):
    # Used only as a hook into FlaskForm's CSRF protection
    pass


class DeleteProductSignoffForm(FlaskForm):
    # Used only as a hook into FlaskForm's CSRF protection
    pass


class ToggleChecklistFeatureForm(FlaskForm):
    # Used only as a hook into FlaskForm's CSRF protection
    pass


class ChooseGithubRepoForm(FlaskForm):
    repo_choice = DSCheckboxField(label="Choose the repositories to connect with", coerce=int)

    def __init__(self, repos=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if repos is None:
            repos = []

        self.repo_choice.choices = [(r.id, r.fullname) for r in repos]


class TransferGithubRepoForm(FlaskForm):
    repo_choice = DSRadioField(label="Transfer repositories to your account", coerce=int)

    def __init__(self, repos=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if repos is None:
            repos = []

        self.repo_choice.choices = [(r.id, r.fullname) for r in repos]


class AuthorizeTrelloForm(FlaskForm):
    trello_integration = StringField(label="Trello Authorisation Token", validators=[DataRequired()])


class ChooseTrelloBoardForm(FlaskForm):
    board_choice = DSRadioField(label="Choose your board", validators=[DataRequired()])

    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if boards is None:
            boards = []

        self.board_choice.choices = [(board.board_id, board.name) for board in boards]


class ChooseTrelloListForm(FlaskForm):
    list_choice = DSRadioField(label="Choose your list", validators=[DataRequired()])

    def __init__(self, lists=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if lists is None:
            lists = []

        self.list_choice.choices = [(l.id, l.name) for l in lists]
