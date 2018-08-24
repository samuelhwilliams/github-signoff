class Unauthorized(Exception):
    pass


class TrelloUnauthorized(Unauthorized):
    pass


class GithubUnauthorized(Unauthorized):
    pass


class HookAlreadyExists(Exception):
    pass
