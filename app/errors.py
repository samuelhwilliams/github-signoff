from requests.exceptions import HTTPError


class Unauthorized(Exception):
    pass


class TrelloUnauthorized(Unauthorized):
    pass


class TrelloInvalidRequest(HTTPError):
    def __init__(self, source=None, *args, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)


class TrelloResourceMissing(Exception):
    pass


class GithubUnauthorized(Unauthorized):
    pass


class GithubResourceMissing(Exception):
    pass


class HookAlreadyExists(Exception):
    pass
