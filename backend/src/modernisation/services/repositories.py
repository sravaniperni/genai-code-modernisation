"""Repository registration with source authorisation."""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from modernisation.config import Settings, get_settings
from modernisation.db.models import Repository
from modernisation.repository_intelligence.git_ops import GitError, GitRepo, mirror_repository
from modernisation.repository_intelligence.indexer import mirror_path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,99}$")
GITHUB_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,38})/[A-Za-z0-9._\-]{1,100}$")


class RepositoryAccessDenied(PermissionError):
    pass


def _authorised_local(path: Path, settings: Settings) -> Path:
    real = Path(os.path.realpath(path))
    for root in settings.allowed_local_roots:
        root_real = Path(os.path.realpath(root))
        if real == root_real or root_real in real.parents:
            return real
    raise RepositoryAccessDenied(f"{path} is not under an authorised local root (MODERNISATION_ALLOWED_LOCAL_ROOTS)")


def authorise_github(full_name: str, settings: Settings) -> None:
    if not GITHUB_RE.match(full_name):
        raise RepositoryAccessDenied(f"invalid repository name {full_name!r}")
    owner = full_name.split("/")[0].lower()
    allowed = {a.lower() for a in settings.allowed_github_repositories}
    if full_name.lower() not in allowed and owner not in allowed:
        raise RepositoryAccessDenied(
            f"{full_name} is not in the authorised repository list (MODERNISATION_ALLOWED_GITHUB_REPOSITORIES)"
        )


def github_git_env(settings: Settings) -> dict[str, str] | None:
    """Pass the token as an HTTP header via environment-only git config (never in URLs or argv)."""
    if settings.github_token is None:
        return None
    import base64

    token = settings.github_token.get_secret_value()
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


def register_local(session: Session, name: str, path: str, settings: Settings | None = None) -> Repository:
    settings = settings or get_settings()
    if not NAME_RE.match(name):
        raise ValueError("repository name must be 1-100 characters of letters, digits, '.', '_' or '-'")
    real = _authorised_local(Path(path), settings)
    if not (real / ".git").exists() and not (real / "HEAD").exists():
        raise ValueError(f"{real} is not a git repository")
    if session.scalar(select(Repository).where(Repository.name == name)):
        raise ValueError(f"repository {name!r} already exists")
    repo = Repository(name=name, source_kind="local", source=str(real), clone_url=str(real))
    session.add(repo)
    session.flush()
    try:
        git = mirror_repository(str(real), mirror_path(repo))
        repo.default_branch = _default_branch(git)
    except GitError:
        session.rollback()
        raise
    session.commit()
    return repo


def register_github(
    session: Session,
    full_name: str,
    settings: Settings | None = None,
    name: str | None = None,
    default_branch: str | None = None,
) -> Repository:
    settings = settings or get_settings()
    authorise_github(full_name, settings)
    name = name or full_name.replace("/", "__")
    if session.scalar(select(Repository).where(Repository.name == name)):
        raise ValueError(f"repository {name!r} already exists")
    repo = Repository(
        name=name,
        source_kind="github",
        source=full_name,
        github_full_name=full_name,
        clone_url=f"https://github.com/{full_name}.git",
    )
    session.add(repo)
    session.flush()
    git = mirror_repository(repo.clone_url, mirror_path(repo), extra_env=github_git_env(settings))
    repo.default_branch = default_branch or _default_branch(git)
    session.commit()
    return repo


def refresh(repo: Repository, settings: Settings | None = None) -> GitRepo:
    settings = settings or get_settings()
    env = github_git_env(settings) if repo.source_kind == "github" else None
    return mirror_repository(repo.clone_url, mirror_path(repo), extra_env=env)


def _default_branch(git: GitRepo) -> str:
    try:
        head = git.git("symbolic-ref", "--short", "HEAD").strip()
        if head:
            return head
    except GitError:
        pass
    branches = git.branches()
    for candidate in ("main", "master"):
        if candidate in branches:
            return candidate
    return next(iter(branches), "main")
