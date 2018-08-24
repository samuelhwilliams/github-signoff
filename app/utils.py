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


def get_github_client(user):
    return GithubClient(client_id=GITHUB_CLIENT_ID, client_secret=GITHUB_CLIENT_SECRET, user=user)


def get_trello_client(user):
    return TrelloClient(key=TRELLO_API_KEY, user=user)


def find_trello_card_ids_in_text(text):
    urls = re.findall(r"(?:https?://)?(?:www.)?trello.com/c/\w+\b", text)
    return {os.path.basename(url) for url in urls}
