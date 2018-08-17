import os

from flask import Flask

from app import db, login_manager, migrate, mail
from app.views import main_blueprint
from app.config import config_map


def create_app():
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_map[os.environ.get("FLASK_ENV", "production")])

    db.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_message = None
    login_manager.login_view = ".start_page"

    app.register_blueprint(main_blueprint)

    return app
