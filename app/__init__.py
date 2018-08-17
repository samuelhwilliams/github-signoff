from flask_breadcrumbs import Breadcrumbs
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sparkpost import SparkPost

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
sparkpost = SparkPost()
breadcrumbs = Breadcrumbs()
