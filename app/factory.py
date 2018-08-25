import os
from functools import partial

from flask import Flask, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import current_user

from app import db, login_manager, migrate
from app.views import main_blueprint
from app.config import config_map
from app.errors import TrelloUnauthorized, GithubUnauthorized


def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_map[os.environ.get("FLASK_ENV", "development")])

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = ".index"

    migrate.init_app(app, db)

    app.register_blueprint(main_blueprint)

    register_error_handlers(app)

    return app


def register_error_handlers(app):
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
