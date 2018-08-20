from flask_wtf import FlaskForm
from wtforms import StringField, SelectField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField(label="Email address", validators=[Email()])


class ChooseGithubRepoForm(FlaskForm):
    repo_choice = SelectField(label="Choose your repository", validators=[DataRequired()], coerce=int)

    def __init__(self, repos=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if repos is None:
            repos = []

        self.repo_choice.choices = [(r["id"], r["name"]) for r in repos]


class AuthorizeTrelloForm(FlaskForm):
    trello_integration = StringField(label="Trello Authorization Token", validators=[DataRequired()])


class ChooseTrelloBoardForm(FlaskForm):
    board_choice = SelectField(label="Choose your board", validators=[DataRequired()])

    def __init__(self, boards=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if boards is None:
            boards = []

        self.board_choice.choices = [(board["id"], board["name"]) for board in boards]


class ChooseTrelloListForm(FlaskForm):
    list_choice = SelectField(label="Choose your list", validators=[DataRequired()])

    def __init__(self, lists=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if lists is None:
            lists = []

        self.list_choice.choices = [(l["id"], l["name"]) for l in lists]
