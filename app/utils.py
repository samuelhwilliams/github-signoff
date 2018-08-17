import logging
import os
import re

from app.github import GithubClient
from app.trello import TrelloClient


logger = logging.getLogger(__name__)


def coerce_boolean_or_error(key, value):
    if isinstance(value, bool):
        return value
    elif value.lower() in ["t", "true", "on", "yes", "1"]:
        return True
    elif value.lower() in ["f", "false", "off", "no", "0"]:
        return False

    raise ValueError("{} must be boolean".format(key))


def coerce_int_or_error(key, value):
    if isinstance(int, value) or isinstance(float, value):
        return value

    try:
        return float(value) if "." in value else int(value)

    except (TypeError, ValueError):
        raise ValueError("{} must be an integer".format(key))


def get_github_client(app, user):
    return GithubClient(
        client_id=app.config["GITHUB_CLIENT_ID"], client_secret=app.config["GITHUB_CLIENT_SECRET"], user=user
    )


def get_trello_client(app, user):
    return TrelloClient(key=app.config["TRELLO_API_KEY"], user=user)


def find_trello_card_ids_in_text(text):
    urls = re.findall(r"(?:https?://)?(?:www.)?trello.com/c/\w+\b", text)
    card_ids = {os.path.basename(url) for url in urls}
    logger.debug(f"Found trello cards: {card_ids}")
    return card_ids


def get_github_token_status(app, user):
    if user.github_token is not None:
        github_client = get_github_client(app, user)
        return "valid" if github_client.is_token_valid() else "invalid"

    return None


def get_trello_token_status(app, user):
    if user.trello_token is not None:
        trello_client = get_trello_client(app, user)
        return "valid" if trello_client.is_token_valid() else "invalid"

    return None
