from urllib.parse import quote_plus

import requests


class TrelloClient:
    TRELLO_API_ROOT = "https://api.trello.com/1"

    def __init__(self, key, token):
        self.key = key
        self.token = token

    def _default_params(self):
        return {"key": self.key, "token": self.token}

    def _request(self, method, path, params=None):
        if params is None:
            params = {}

        params = {**self._default_params(), **params}

        response = requests.request(
            method=method, url=f"{TrelloClient.TRELLO_API_ROOT}/{path}", params=params
        )

        return response.json()

    def _get(self, path, params=None):
        return self._request("get", path, params)

    def _post(self, path, params=None):
        return self._request("post", path, params)

    def _me(self):
        return self._get("members/me")

    def get_boards(self):
        board_ids = self._me()["idBoards"]

        boards = []
        for board_id in board_ids:
            boards.append(self._get(f"/boards/{board_id}"))

        return [
            {"id": board["id"], "name": board["name"], "url": board["shortUrl"]}
            for board in boards
        ]

    def get_board(self, board_id):
        pass

    def get_lists(self, board_id):
        lists = self._get(f"/boards/{board_id}/lists")

        return [{"id": l["id"], "name": l["name"]} for l in lists]

    def create_webhook(
        self,
        object_id,
        callback_url,
        description="github-signoff-callback",
        active=True,
    ):
        response = self._post(
            "webhooks",
            params={
                "idModel": object_id,
                "description": description,
                "callbackURL": callback_url,
                "active": active,
            },
        )

        return response
