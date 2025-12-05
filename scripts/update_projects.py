#!/usr/bin/env python3
import os
import json
import time
import requests
from urllib.parse import urljoin

"""
GitHub Pages を公開しているリポジトリを収集し、_data/projects.json を生成します。
出力JSONには name, url (Pages), github_url (GitHubリポジトリURL), description, updated_at, stars, language を含みます。

環境変数:
- GITHUB_TOKEN (推奨): GitHub API 用トークン。未設定でも public 情報取得は可能（低レート制限）。
- GITHUB_OWNER (必須): 対象ユーザー（または Organization）名。例: "Aotumuri"
- GITHUB_EXCLUDE_REPOS (任意): カンマ区切りで除外するリポジトリ名を指定
- GITHUB_SELF_REPO (任意): 自身のリポジトリ名を明示したい場合に指定（未指定ならカレントディレクトリ名を使用）

使い方:
  python scripts/update_projects.py
"""

API_BASE = "https://api.github.com"

OWNER = os.getenv("GITHUB_OWNER")
if not OWNER:
    raise SystemExit("ERROR: GITHUB_OWNER が未設定です。環境変数で設定してください。")
OWNER_LOWER = OWNER.lower()

exclude_env = os.getenv("GITHUB_EXCLUDE_REPOS", "")
EXCLUDE_REPOS = {
    name.strip().lower() for name in exclude_env.split(",") if name.strip()
}
self_repo = os.getenv("GITHUB_SELF_REPO") or os.path.basename(os.getcwd())
if self_repo:
    EXCLUDE_REPOS.add(self_repo.lower())
EXCLUDE_FULL_NAMES = {f"{OWNER_LOWER}/{name}" for name in EXCLUDE_REPOS}

TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.timeout = 30

def gh_get(url, params=None, ok_codes=(200,)):
    for attempt in range(3):
        r = SESSION.get(url, params=params)
        if r.status_code in ok_codes:
            return r
        # レート制限や一時エラーへの簡易リトライ
        time.sleep(1.5 * (attempt + 1))
    r.raise_for_status()

def list_public_repos(owner: str):
    # 公開リポを全件ページネーションで取得
    # /users/:owner/repos は public のみ。per_page=100 で回収。
    repos = []
    page = 1
    while True:
        url = f"{API_BASE}/users/{owner}/repos"
        params = {"per_page": 100, "page": page, "type": "public", "sort": "pushed"}
        r = gh_get(url, params=params)
        chunk = r.json()
        if not chunk:
            break
        repos.extend(chunk)
        page += 1
    return repos

def get_pages_url(owner: str, repo_name: str, has_pages: bool):
    """
    可能なら /repos/{owner}/{repo}/pages の html_url / cname を使う。
    失敗したらデフォルト推定 URL にフォールバック。
    """
    if not has_pages:
        return None

    # ユーザー/Org サイト用の特殊名
    special_root = f"{owner.lower()}.github.io"
    if repo_name.lower() == special_root:
        return f"https://{special_root}/"

    # まずは Pages API で正確な URL を試みる（custom domain 対応）
    pages_api = f"{API_BASE}/repos/{owner}/{repo_name}/pages"
    try:
        r = gh_get(pages_api, ok_codes=(200, 403, 404))  # 403/404 はフォールバックへ
        if r.status_code == 200:
            data = r.json()
            if "html_url" in data and data["html_url"]:
                return data["html_url"].rstrip("/") + "/"
            # cname がある場合はそちらを優先
            if "cname" in data and data["cname"]:
                return f"https://{data['cname'].rstrip('/')}/"
    except requests.RequestException:
        pass

    # フォールバック: 既定の project pages URL 形式
    return f"https://{owner}.github.io/{repo_name}/"

def main():
    repos = list_public_repos(OWNER)

    pages_projects = []
    for repo in repos:
        if not repo.get("has_pages"):
            continue
        if repo.get("archived"):
            # デフォルトではアーカイブを除外（必要なら外してください）
            continue
        repo_name = repo["name"]
        full_name = repo.get("full_name", f"{OWNER}/{repo_name}").lower()
        if repo_name.lower() in EXCLUDE_REPOS or full_name in EXCLUDE_FULL_NAMES:
            continue

        name = repo_name
        url = get_pages_url(OWNER, repo_name, has_pages=True)
        description = repo.get("description") or ""
        updated_at = repo.get("pushed_at") or repo.get("updated_at") or ""
        stargazers = repo.get("stargazers_count", 0)
        language = repo.get("language") or ""
        github_url = repo.get("html_url") or f"https://github.com/{OWNER}/{name}"

        pages_projects.append(
            {
                "name": name,
                "url": url,
                "github_url": github_url,
                "description": description,
                "updated_at": updated_at,
                "stars": stargazers,
                "language": language,
            }
        )

    # 更新日時で降順ソート（最近更新したものを上に）
    pages_projects.sort(key=lambda x: x["updated_at"] or "", reverse=True)

    os.makedirs("_data", exist_ok=True)
    out_path = "_data/projects.json"
    old = None
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            try:
                old = json.load(f)
            except Exception:
                old = None

    # 差分がなければファイル更新しない（無駄コミット防止）
    if old == pages_projects:
        print("No changes in _data/projects.json")
        return

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(pages_projects, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Wrote {out_path} with {len(pages_projects)} projects.")

if __name__ == "__main__":
    main()
