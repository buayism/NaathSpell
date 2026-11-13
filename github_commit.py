"""
github_commit.py — Commit a new word to user_additions.tsv on GitHub.

Uses the GitHub REST API (Contents endpoint) so no git binary is needed.
Requires a GitHub personal access token with 'contents' write permission.

Configuration is read from Streamlit secrets (st.secrets) with these keys:
    [github]
    token = "ghp_..."
    repo  = "owner/repo-name"
    branch = "main"            # optional, defaults to "main"
"""

import base64
import json
import urllib.request
import urllib.error
from typing import Optional


_API = "https://api.github.com"
_FILE_PATH = "user_additions.tsv"   # path inside the repo


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }


def _get_file(token: str, repo: str, branch: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch the current content and SHA of _FILE_PATH.
    Returns (content_str, sha) or (None, None) if the file doesn't exist yet.
    """
    url = f"{_API}/repos/{repo}/contents/{_FILE_PATH}?ref={branch}"
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def commit_word(word: str, freq: int, token: str, repo: str,
                branch: str = "main") -> dict:
    """
    Append ``word<TAB>freq`` to user_additions.tsv on GitHub and commit.

    Returns the GitHub API response dict on success, or raises on failure.
    """
    # 1. Get current file (if it exists)
    content, sha = _get_file(token, repo, branch)

    # 2. Append the new line
    new_line = f"{word}\t{freq}\n"
    if content is None:
        updated = new_line
    else:
        # Make sure there's a trailing newline before appending
        if not content.endswith("\n"):
            content += "\n"
        updated = content + new_line

    # 3. Base64-encode the updated content
    encoded = base64.b64encode(updated.encode("utf-8")).decode("ascii")

    # 4. Build the commit payload
    commit_msg = f"Add word: {word}"
    payload: dict = {
        "message": commit_msg,
        "content": encoded,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha  # required when updating an existing file

    # 5. PUT to create/update the file
    url = f"{_API}/repos/{repo}/contents/{_FILE_PATH}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_headers(token),
                                method="PUT")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
