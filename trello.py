import requests
from errors import TrelloUnauthorized, HookAlreadyExists


class TrelloClient:
    TRELLO_API_ROOT = "https://api.trello.com/1"

    def __init__(self, key, user):
        self.key = key
        self.user = user
        self._token = self.user.trello_token

    def _default_params(self):
        return {"key": self.key, "token": self._token}

    def _request(self, method, path, params=None):
        if params is None:
            params = {}

        params = {**self._default_params(), **params}

        print(f"trello calling out: {path}")
        response = requests.request(method=method, url=f"{TrelloClient.TRELLO_API_ROOT}/{path}", params=params)
        if response.status_code == 401:
            raise TrelloUnauthorized(response.text)

        return response

    def _get(self, *args, **kwargs):
        return self._request("get", *args, **kwargs)

    def _post(self, *args, **kwargs):
        return self._request("post", *args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self._request("delete", *args, **kwargs)

    def _me(self):
        return self._get("/members/me").json()

    def get_board(self, board_id):
        data = self._get(f"/boards/{board_id}").json()

        return {"id": data["id"], "name": data["name"]}

    def get_boards(self):
        board_ids = self._me()["idBoards"]

        boards = []
        for board_id in board_ids:
            boards.append(self._get(f"/boards/{board_id}").json())

        return [{"id": board["id"], "name": board["name"], "url": board["shortUrl"]} for board in boards]

    def get_list(self, list_id):
        data = self._get(f"/lists/{list_id}").json()

        return {"id": data["id"], "name": data["name"], "idBoard": data["idBoard"]}

    def get_card_list(self, card_id):
        data = self._get(f"/cards/{card_id}/list").json()

        return {"id": data["id"], "name": data["name"], "idBoard": data["idBoard"]}

    def get_lists(self, board_id):
        lists = self._get(f"/boards/{board_id}/lists").json()

        return [{"id": l["id"], "name": l["name"]} for l in lists]

    def create_webhook(self, object_id, callback_url, description="product-signoff-callback", active=True):
        response = self._post(
            "webhooks",
            params={"idModel": object_id, "description": description, "callbackURL": callback_url, "active": active},
        )

        if (
            response.status_code == 400
            and response.text == "A webhook with that callback, model, and token already exists"
        ):
            raise HookAlreadyExists(response.text)

        return response.json()

    def delete_webhook(self, hook_id):
        response = self._delete(f"/webhooks/{hook_id}").json()

        return response

    def is_token_valid(self):
        return self._get(f"/tokens/{self._token}").status_code == 200

    def revoke_integration(self):
        return self._delete(f"/tokens/{self._token}").status_code == 200
