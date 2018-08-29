from flask import current_app
import requests
from urllib.parse import urlparse

from app.errors import GithubUnauthorized
from app.models import PullRequest, GithubRepo


class GithubClient:
    GITHUB_API_ROOT = "https://api.github.com"

    def __init__(self, client_id, client_secret, user):
        if user.github_integration is None or user.github_integration.oauth_token is None:
            raise GithubUnauthorized("User has not completed OAuth process")

        self.client_id = client_id
        self.client_secret = client_secret
        self.user = user
        self._token = self.user.github_integration.oauth_token

    def _default_params(self):
        return {"per_page": 100}

    def _default_headers(self, use_basic_auth=False):
        default_headers = {"Accept": "application/vnd.github.v3+json"}

        if not use_basic_auth:
            default_headers["Authorization"] = f"Bearer {self._token}"

        return default_headers

    def _default_auth(self, use_basic_auth=False):
        return (self.client_id, self.client_secret) if use_basic_auth else tuple()

    def _request(self, method, path, params=None, json=None, use_basic_auth=False):
        if params is None:
            params = {}

        params = {**self._default_params(), **params}

        if not path.startswith(self.GITHUB_API_ROOT):
            path = self.GITHUB_API_ROOT + path

        current_app.logger.debug(
            f"Request settings: {method}, {path}, {params}".replace(self._token, "<TOKEN REDACTED>")
        )
        response = requests.request(
            method=method,
            url=path,
            params=params,
            json=json,
            headers=self._default_headers(use_basic_auth=use_basic_auth),
            auth=self._default_auth(use_basic_auth=use_basic_auth),
        )
        if current_app.config["DEBUG_PAYLOADS"]:
            current_app.logger.debug(f"Response: {response.status_code}, {response.text}")

        if response.status_code == 401:
            raise GithubUnauthorized(response.text)

        return response

    def _get(self, *args, **kwargs):
        return self._request("get", *args, **kwargs)

    def _post(self, *args, **kwargs):
        return self._request("post", *args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self._request("delete", *args, **kwargs)

    def get_repos(self):
        response = self._get(f"/user/repos")
        all_repos = [GithubRepo.from_json(data=repo) for repo in response.json() if repo["permissions"]["admin"]]

        while response.links.get("next"):
            response = self._get(response.links["next"]["url"])
            all_repos.extend(
                [GithubRepo.from_json(data=repo) for repo in response.json() if repo["permissions"]["admin"]]
            )

        return all_repos

    def get_repo(self, repo_id, as_json=False):
        data = self._get(f"/repositories/{repo_id}").json()

        if as_json:
            return data

        return GithubRepo.from_json(data=data)

    def get_pull_request(self, repo_id, pull_request_id, as_json=False):
        # TODO: Fix this crap proxy lookup
        data = self._get(f"/repositories/{repo_id}").json()
        data = self._get(f"/repos/{data['full_name']}/pulls/{pull_request_id}").json()

        if as_json:
            return data

        return PullRequest.from_json(data=data)

    def create_webhook(self, repo_id, callback_url, secret, events=["pull_request"], active=True):
        response = self._post(
            f"/repositories/{repo_id}/hooks",
            json={
                "name": "web",
                "config": {"content_type": "json", "url": callback_url, "secret": secret},
                "events": events,
                "active": active,
            },
        ).json()

        return response

    def delete_webhook(self, repo_id, hook_id):
        response = self._delete(f"/repositories/{repo_id}/hooks/{hook_id}")

        return response

    def set_pull_request_status(self, statuses_url, status, description, context, target_url=""):
        return self._post(
            urlparse(statuses_url).path,
            json={"state": status, "description": description, "context": context, "target_url": target_url},
        )

    def is_token_valid(self):
        response = self._get(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True)
        return response.status_code == 200

    def revoke_integration(self):
        return (
            self._delete(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True).status_code == 204
        )
