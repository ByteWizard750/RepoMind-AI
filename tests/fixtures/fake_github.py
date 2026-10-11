"""An in-memory GitHub REST API for issue tests (an httpx.MockTransport):
just the repository, label and issue endpoints review/github_issues.py uses."""
import json
import re

import httpx


class FakeGitHub:
    def __init__(self, slug="owner/repo", permissions=None, has_issues=True):
        self.slug = slug
        self.permissions = {"admin": False, "maintain": False, "push": True, "triage": False, "pull": True} \
            if permissions is None else permissions
        self.has_issues = has_issues
        self.issues = {}
        self.comments = []
        self.labels = set()
        self.requests = []
        self.next_number = 1

    def add_issue(self, title, body, state="open", labels=("repomind-review",)):
        number = self.next_number
        self.next_number += 1
        self.issues[number] = {"number": number, "title": title, "body": body, "state": state,
                               "labels": [{"name": n} for n in labels],
                               "html_url": f"https://github.com/{self.slug}/issues/{number}"}
        return self.issues[number]

    def transport(self):
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path, request.headers.get("authorization")))
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        base = f"/repos/{self.slug}"
        if method == "GET" and path == base:
            repo = {"full_name": self.slug, "html_url": f"https://github.com/{self.slug}", "has_issues": self.has_issues}
            if self.permissions is not False:
                repo["permissions"] = self.permissions
            return httpx.Response(200, json=repo)
        if not path.startswith(base):
            return httpx.Response(404, json={"message": "Not Found"})
        if method == "GET" and path == f"{base}/issues":
            label = request.url.params.get("labels")
            page = int(request.url.params.get("page", "1"))
            items = [i for i in self.issues.values() if any(lb["name"] == label for lb in i["labels"])]
            return httpx.Response(200, json=items[(page - 1) * 100:page * 100])
        if method == "POST" and path == f"{base}/labels":
            if body["name"] in self.labels:
                return httpx.Response(422, json={"message": "Validation Failed"})
            self.labels.add(body["name"])
            return httpx.Response(201, json={"name": body["name"]})
        if method == "POST" and path == f"{base}/issues":
            return httpx.Response(201, json=self.add_issue(body["title"], body["body"], labels=body.get("labels", [])))
        m = re.fullmatch(rf"{base}/issues/(\d+)(/comments)?", path)
        if m and int(m.group(1)) in self.issues:
            issue = self.issues[int(m.group(1))]
            if m.group(2) and method == "POST":
                self.comments.append((issue["number"], body["body"]))
                return httpx.Response(201, json={"id": len(self.comments)})
            if method == "PATCH":
                issue.update({k: v for k, v in body.items() if k in ("state", "title", "body")})
                return httpx.Response(200, json=issue)
        return httpx.Response(404, json={"message": "Not Found"})
