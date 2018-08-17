import requests

from app.errors import GithubUnauthorized
from app.models import PullRequestStatus, GithubRepo


class GithubClient:
    GITHUB_API_ROOT = "https://api.github.com"

    def __init__(self, client_id, client_secret, user):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user = user
        self._token = self.user.github_token

    def _default_params(self):
        return {"access_token": self._token}

    def _default_headers(self):
        return {"Accept": "application/vnd.github.v3+json"}

    def _request(self, method, path, params=None, json=None, use_basic_auth=False):
        if params is None:
            params = {}

        params = {**self._default_params(), **params}

        print("Request settings: ", method, path, params)
        response = requests.request(
            method=method,
            url=f"{GithubClient.GITHUB_API_ROOT}{path}",
            params=params,
            json=json,
            headers=self._default_headers(),
            auth=(self.client_id, self.client_secret) if use_basic_auth else tuple(),
        )
        print("Response: ", response.text)

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
        data = self._get(f"/user/repos").json()

        repos = [
            GithubRepo.from_json(user=self.user, data=repo_data)
            for repo_data in data
            if repo_data["permissions"]["admin"]
        ]
        return repos

    def get_repo(self, repo_id, as_json=False):
        data = self._get(f"/repositories/{repo_id}").json()

        if as_json:
            return data

        return GithubRepo.from_json(user=self.user, data=data)

    def get_pull_request(self, repository_id, pull_request_id, as_json=False):
        data = self._get(f"/repositories/{pull_request_id}/").json()

        if as_json:
            return data

        return PullRequestStatus.from_json(user=self.user, data=data)

    def create_webhook(self, repo_id, callback_url, events=["pull_request"], active=True):
        response = self._post(
            f"/repositories/{repo_id}/hooks",
            json={
                "name": "web",
                "config": {"content_type": "json", "url": callback_url},
                "events": events,
                "active": active,
            },
        ).json()

        return response

    def delete_webhook(self, repo_id, hook_id):
        response = self._delete(f"/repositories/{repo_id}/hooks/{hook_id}")

        return response

    def set_pull_request_status(self, repo_id, sha, status, description, context, target_url=""):
        return self._post(
            f"/repositories/{repo_id}/statuses/{sha}",
            json={"state": status, "description": description, "context": context, "target_url": target_url},
        )

    def is_token_valid(self):
        response = self._get(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True)
        return response.status_code == 200

    def revoke_integration(self):
        return (
            self._delete(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True).status_code == 204
        )
