import os
import re

from flask import current_app

from app.errors import TrelloInvalidRequest, TrelloResourceMissing
from app.github import GithubClient
from app.trello import TrelloClient


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


def get_trello_cards_from_text(trello_client, text):
    urls = re.findall(r"(?:https?://)?(?:www.)?trello.com/c/\w+\b", text)
    card_ids = {os.path.basename(url) for url in urls}

    trello_cards = []
    for card_id in card_ids:
        try:
            trello_card = trello_client.get_card(card_id)

        except (TrelloInvalidRequest, TrelloResourceMissing):
            current_app.logger.warn(f"Ignoring invalid card {card_id}")
            continue

        trello_cards.append(trello_card)

    current_app.logger.debug(f"Found trello cards: {trello_cards}")
    return trello_cards


def get_github_token_status(app, user):
    if user.github_integration is not None and user.github_integration.oauth_token is not None:
        github_client = get_github_client(app, user)
        return "valid" if github_client.is_token_valid() else "invalid"

    return None


def get_trello_token_status(app, user):
    if user.trello_integration is not None and user.trello_integration.oauth_token is not None:
        trello_client = get_trello_client(app, user)
        return "valid" if trello_client.is_token_valid() else "invalid"

    return None
