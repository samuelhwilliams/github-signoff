from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from sparkpost import SparkPost

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
mail = Mail()
sparkpost = SparkPost()
