import requests

from flask import current_app

from app.models import TrelloBoard, TrelloList, TrelloCard, TrelloChecklist, TrelloCheckitem
from app.errors import TrelloUnauthorized, HookAlreadyExists, TrelloInvalidRequest, TrelloResourceMissing


BOARD_FIELD_PARAMS = {"board": "true", "board_fields": "id,name"}
LIST_FIELD_PARAMS = {"list": "true", "list_fields": "id,name,idBoard"}
CARD_FIELD_PARAMS = {"card": "true", "card_fields": "shortLink,name"}


class TrelloClient:
    TRELLO_API_ROOT = "https://api.trello.com/1"

    def __init__(self, key, user):
        if user.trello_integration is None or user.trello_integration.oauth_token is None:
            raise TrelloUnauthorized("User has not completed OAuth process")

        self.key = key
        self.user = user
        self._token = self.user.trello_integration.oauth_token

    def _default_params(self):
        return {"key": self.key, "token": self._token}

    def _request(self, method, path, params=None):
        if params is None:
            params = {}

        all_params = {**self._default_params(), **params}

        current_app.logger.debug(f"Request settings: {method}, {path}, {params}")
        response = requests.request(method=method, url=f"{TrelloClient.TRELLO_API_ROOT}{path}", params=all_params)
        current_app.logger.debug(f"Response: {response.status_code}, {response.text}")

        if response.status_code == 401:
            raise TrelloUnauthorized(response.text)
        elif response.status_code == 404:
            raise TrelloResourceMissing(response.text)
        elif response.status_code == 400 or response.status_code % 100 == 5:
            try:
                response.raise_for_status()

            except requests.exceptions.HTTPError as e:
                current_app.logger.error(f"{method}, {path}, {params}")
                raise TrelloInvalidRequest(source=e)

        return response

    def _get(self, path=None, params=None):
        return self._request("get", path, params)

    def _put(self, path=None, params=None):
        return self._request("put", path, params)

    def _post(self, path=None, params=None):
        return self._request("post", path, params)

    def _delete(self, path=None, params=None):
        return self._request("delete", path, params)

    def _me(self):
        return self._get("/members/me").json()

    def get_board(self, board_id, as_json=False):
        data = self._get(f"/boards/{board_id}").json()

        if as_json:
            return data

        return TrelloBoard.from_json(data)

    def get_boards(self, with_lists=False):
        params = {"lists": "all"} if with_lists else {}
        boards = self._get(f"/members/me/boards", params=params).json()

        return [TrelloBoard.from_json(board_data) for board_data in boards]

    def get_list(self, list_id, as_json=False):
        data = self._get(f"/lists/{list_id}").json()

        if as_json:
            return data

        return TrelloList.from_json(data)

    def get_card(self, card_id, as_json=False):
        data = self._get(
            f"/cards/{card_id}", params={**BOARD_FIELD_PARAMS, **LIST_FIELD_PARAMS, **CARD_FIELD_PARAMS}
        ).json()

        if as_json:
            return data

        return TrelloCard.from_json(data)

    def get_lists(self, board_id):
        lists = self._get(f"/boards/{board_id}/lists", params={**BOARD_FIELD_PARAMS}).json()
        return [TrelloList.from_json(data) for data in lists]

    def get_webhook(self, object_id):
        webhooks = self._get(f"/tokens/{self._token}/webhooks").json()

        for webhook in webhooks:
            if webhook["idModel"] == object_id:
                return webhook

        raise TrelloResourceMissing(f"Wanted webhook on {object_id}. Got: {webhooks}")

    def create_webhook(self, object_id, callback_url, description="product-signoff-callback", active=True):
        try:
            response = self._post(
                "/webhooks",
                params={
                    "idModel": object_id,
                    "description": description,
                    "callbackURL": callback_url,
                    "active": active,
                },
            )

        except TrelloInvalidRequest as e:
            if (
                e.source
                and e.source.response.status_code == 400
                and e.source.response.text == "A webhook with that callback, model, and token already exists"
            ):
                raise HookAlreadyExists(e.source.response.text)

        return response.json()

    def delete_webhook(self, hook_id):
        response = self._delete(f"/webhooks/{hook_id}").json()

        return response

    def create_checklist(self, real_card_id, checklist_name, pos="bottom"):
        data = self._post("/checklists", params={"idCard": real_card_id, "name": checklist_name, "pos": pos}).json()

        return TrelloChecklist.from_json(data)

    def get_checklist(self, checklist_id, as_json=False):
        data = self._get(f"/checklists/{checklist_id}").json()

        if as_json:
            return data

        return TrelloChecklist.from_json(data)

    def delete_checklist(self, checklist_id):
        response = self._delete(f"/checklists/{checklist_id}")

        return response

    def create_checkitem(self, checklist_id, checkitem_name, pos="bottom", checked="false"):
        data = self._post(
            f"/checklists/{checklist_id}/checkItems", params={"name": checkitem_name, "pos": pos, "checked": checked}
        ).json()

        return TrelloCheckitem.from_json(data)

    def update_checkitem(self, real_card_id, checkitem_id, state="incomplete"):
        data = self._put(f"/cards/{real_card_id}/checkItem/{checkitem_id}", params={"state": state}).json()

        return TrelloCheckitem.from_json(data)

    def get_checkitem(self, checklist_id, checkitem_id, as_json=False):
        data = self._get(f"/checklists/{checklist_id}/checkItems/{checkitem_id}").json()

        if as_json:
            return data

        return TrelloCheckitem.from_json(data)

    def delete_checkitem(self, checklist_id, checkitem_id):
        response = self._delete(f"/checklists/{checklist_id}/checkItems/{checkitem_id}")

        return response

    def is_token_valid(self):
        try:
            return self._get(f"/tokens/{self._token}").status_code == 200

        except TrelloUnauthorized:
            return False

    def revoke_integration(self):
        return self._delete(f"/tokens/{self._token}").status_code == 200
