import requests
from datetime import datetime
from dateutil.parser import parse

class GitLabClient:
    def __init__(self, base_url, pat):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "PRIVATE-TOKEN": pat
        })

    def _get(self, path, params=None):
        url = f"{self.base_url}/api/v4{path}"
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_groups(self):
        return self._get("/groups", params={"all_available": True, "per_page": 100})

    def get_projects(self, group_id):
        return self._get(f"/groups/{group_id}/projects", params={"per_page": 100})

    def get_merge_requests(self, project_id, states):
        mrs = []
        for state in states:
            mrs.extend(
                self._get(
                    f"/projects/{project_id}/merge_requests",
                    params={"state": state, "per_page": 100}
                )
            )
        return mrs

    def get_commits(self, project_id, mr_iid):
        return self._get(
            f"/projects/{project_id}/merge_requests/{mr_iid}/commits"
        )

    def get_diff_stats(self, project_id, mr_iid):
        changes = self._get(
            f"/projects/{project_id}/merge_requests/{mr_iid}/changes"
        )
        additions = sum(f["additions"] for f in changes["changes"])
        deletions = sum(f["deletions"] for f in changes["changes"])
        return additions + deletions

    def get_user_comments_count(self, project_id, mr_iid):
        notes = self._get(
            f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            params={"per_page": 100}
        )
        return sum(1 for n in notes if not n.get("system", False))

    @staticmethod
    def days_since(date_str):
        created = parse(date_str)
        return (datetime.utcnow() - created.replace(tzinfo=None)).days