import requests

from errors import GithubUnauthorized


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

        response = requests.request(
            method=method,
            url=f"{GithubClient.GITHUB_API_ROOT}{path}",
            params=params,
            json=json,
            headers=self._default_headers(),
            auth=(self.client_id, self.client_secret) if use_basic_auth else tuple(),
        )

        if response.status_code == 401:
            raise GithubUnauthorized(response.text)

        return response

    def _get(self, *args, **kwargs):
        return self._request("get", *args, **kwargs)

    def _post(self, *args, **kwargs):
        print(args)
        print(kwargs)
        return self._request("post", *args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self._request("delete", *args, **kwargs)

    def get_repos(self):
        data = self._get(f"/user/repos").json()

        repos = [{"id": repo["id"], "name": repo["full_name"]} for repo in data if repo["permissions"]["admin"]]
        return repos

    def create_webhook(self, repo_fullname, callback_url, events=["pull_request"], active=True):
        response = self._post(
            f"/repos/{repo_fullname}/hooks",
            json={
                "name": "web",
                "config": {"content_type": "json", "url": callback_url},
                "events": events,
                "active": active,
            },
        ).json()

        return response

    def delete_webhook(self, repo_fullname, hook_id):
        response = self._delete(f"/repos/{repo_fullname}/hooks/{hook_id}")

        return response

    def set_pull_request_status(self, repo_fullname, sha, status, description, context, target_url=""):
        return self._post(
            f"/repos/{repo_fullname}/statuses/{sha}",
            json={"state": status, "description": description, "context": context, "target_url": target_url},
        )

    def is_token_valid(self):
        response = self._get(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True)
        return response.status_code == 200

    def revoke_integration(self):
        return (
            self._delete(f"/applications/{self.client_id}/tokens/{self._token}", use_basic_auth=True).status_code == 204
        )
