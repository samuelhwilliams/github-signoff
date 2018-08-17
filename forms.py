from flask_wtf import FlaskForm
from wtforms import StringField, SelectField
from wtforms.validators import DataRequired, Email


class LoginForm(FlaskForm):
    email = StringField(label="Email address", validators=[Email()])


class AuthorizeTrelloForm(FlaskForm):
    trello_auth_key = StringField(
        label="Trello Authorization Token", validators=[DataRequired()]
    )


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
