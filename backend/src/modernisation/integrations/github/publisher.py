"""Idempotent publication of verified changes as draft pull requests.

Each external side effect is recorded in the ``external_actions`` ledger under a deterministic
idempotency key *before* it is attempted:

1. ``commit``              build a deterministic commit (fixed author/committer dates) from base + diff
2. ``push_branch``         push it to ``modernisation/task-<id>-<slug>``; an existing remote branch at the same
                           SHA counts as done, a different SHA is a conflict (never force-pushed)
3. ``create_pull_request`` look up an existing PR for the head branch first; create only if none exists;
                           after a timeout the outcome is reconciled by lookup, never by blind retry
4. ``report_status``       publish the verification result as a commit status

Because the commit is deterministic and every step reconciles against the remote before acting, a crash
or timeout at any point can be retried without creating duplicate branches or pull requests.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modernisation.agents.store import add_event
from modernisation.config import Settings, get_settings
from modernisation.db.models import ExternalAction, Task
from modernisation.execution.policy import ChangePolicy
from modernisation.execution.workspace import Workspace
from modernisation.integrations.github.client import GitHubClient, GitHubError
from modernisation.repository_intelligence.git_ops import GitError, run_git
from modernisation.repository_intelligence.indexer import git_for
from modernisation.services.repositories import github_git_env


class PublishError(RuntimeError):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


def branch_name(task: Task) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40] or "change"
    return f"modernisation/task-{task.id}-{slug}"


def _ledger(
    session: Session,
    task: Task,
    kind: str,
    key: str,
    request: dict[str, Any],
    perform: Callable[[ExternalAction], dict[str, Any]],
) -> dict[str, Any]:
    action = session.scalar(select(ExternalAction).where(ExternalAction.idempotency_key == key))
    if action is not None and action.status == "succeeded":
        return dict(action.response or {})
    if action is None:
        action = ExternalAction(task_id=task.id, kind=kind, idempotency_key=key, request=request, status="pending")
        session.add(action)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            action = session.scalar(select(ExternalAction).where(ExternalAction.idempotency_key == key))
            assert action is not None
            if action.status == "succeeded":
                return dict(action.response or {})
    action.attempts += 1
    session.commit()
    try:
        response = perform(action)
    except Exception as exc:
        action.status = "failed" if not getattr(exc, "retryable", True) else "pending"
        action.error = str(exc)[:2000]
        session.commit()
        raise
    action.status = "succeeded"
    action.response = response
    action.external_ref = str(response.get("ref") or response.get("url") or "")
    action.error = None
    session.commit()
    add_event(
        session,
        task.id,
        "external",
        f"{kind} succeeded",
        state=task.state,
        payload={"kind": kind, "key": key, "ref": action.external_ref, "attempts": action.attempts},
    )
    session.commit()
    return response


class Publisher:
    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: Callable[[], GitHubClient] | None = None,
        push_url: Callable[[Task], str] | None = None,
    ):
        self.settings = settings or get_settings()
        self.client_factory = client_factory or self._default_client
        self.push_url = push_url or (lambda task: f"https://github.com/{task.repository.github_full_name}.git")

    def _default_client(self) -> GitHubClient:
        if self.settings.github_token is None:
            raise PublishError("MODERNISATION_GITHUB_TOKEN is not configured", retryable=False)
        return GitHubClient(
            base_url=self.settings.github_api_url,
            token=self.settings.github_token.get_secret_value(),
            timeout_s=self.settings.github_timeout_s,
        )

    def publish(self, session: Session, task: Task) -> dict[str, Any]:
        if task.repository.source_kind != "github":
            return self._publish_local(session, task)
        return self._publish_github(session, task)

    # ------------------------------------------------------------------------------------------------
    def _commit(self, session: Session, task: Task) -> str:
        diff = task.final_diff or ""
        digest = hashlib.sha256(diff.encode()).hexdigest()[:16]

        def make_commit(_: ExternalAction) -> dict[str, Any]:
            ws = Workspace(
                f"task-{task.id}", git_for(task.repository), task.base_commit, self.settings, label="publish"
            )
            ws.destroy()
            ws.create()
            ws.apply_diff(
                diff,
                ChangePolicy(
                    allowed_paths=list(task.allowed_paths or []), forbidden_paths=list(task.forbidden_paths or [])
                ),
            )
            stamp = task.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            env = {
                "GIT_AUTHOR_NAME": self.settings_git_name(),
                "GIT_AUTHOR_EMAIL": self.settings_git_email(),
                "GIT_COMMITTER_NAME": self.settings_git_name(),
                "GIT_COMMITTER_EMAIL": self.settings_git_email(),
                "GIT_AUTHOR_DATE": stamp,
                "GIT_COMMITTER_DATE": stamp,
            }
            message = f"{task.category.replace('_', ' ')}: {task.title}\n\nMaintenance task #{task.id}."
            run_git(["-c", "safe.directory=*", "add", "-A"], cwd=ws.repo_dir)
            run_git(
                ["-c", "safe.directory=*", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", message],
                cwd=ws.repo_dir,
                env=env,
            )
            sha = run_git(["-c", "safe.directory=*", "rev-parse", "HEAD"], cwd=ws.repo_dir).stdout.decode().strip()
            # keep the commit in the platform mirror so later steps can push it without the workspace
            run_git(
                [
                    "-c",
                    "safe.directory=*",
                    "push",
                    "--quiet",
                    str(git_for(task.repository).path),
                    f"{sha}:refs/modernisation/task-{task.id}",
                ],
                cwd=ws.repo_dir,
            )
            ws.destroy()
            return {"sha": sha, "ref": sha}

        result = _ledger(
            session, task, "commit", f"task:{task.id}:commit:{digest}", {"diff_sha256": digest}, make_commit
        )
        return str(result["sha"])

    def settings_git_name(self) -> str:
        return self.settings.git_author_name

    def settings_git_email(self) -> str:
        return self.settings.git_author_email

    def _publish_local(self, session: Session, task: Task) -> dict[str, Any]:
        sha = self._commit(session, task)
        branch = task.branch_name or branch_name(task)

        def create_branch(_: ExternalAction) -> dict[str, Any]:
            mirror = git_for(task.repository).path
            run_git(["update-ref", f"refs/heads/{branch}", sha], cwd=mirror)
            return {
                "branch": branch,
                "sha": sha,
                "ref": f"refs/heads/{branch}",
                "note": "branch created in the platform mirror only; the source repository was not modified",
            }

        result = _ledger(
            session,
            task,
            "create_branch",
            f"task:{task.id}:local-branch:{branch}:{sha}",
            {"branch": branch, "sha": sha},
            create_branch,
        )
        task.branch_name = branch
        session.commit()
        return {"kind": "local", **result}

    def _publish_github(self, session: Session, task: Task) -> dict[str, Any]:
        full_name = task.repository.github_full_name
        assert full_name
        client = self.client_factory()
        try:
            perms = client.permissions(full_name)
            if not perms.get("push"):
                raise PublishError(f"the configured token cannot push to {full_name}", retryable=False)
            sha = self._commit(session, task)
            branch = task.branch_name or branch_name(task)
            task.branch_name = branch
            session.commit()

            def push(_: ExternalAction) -> dict[str, Any]:
                remote_sha = client.get_branch_sha(full_name, branch)
                if remote_sha == sha:
                    return {"branch": branch, "sha": sha, "ref": branch, "reconciled": True}
                if remote_sha is not None:
                    raise PublishError(
                        f"remote branch {branch} exists at {remote_sha}, expected {sha}; refusing to overwrite",
                        retryable=False,
                    )
                try:
                    run_git(
                        ["push", "--quiet", self.push_url(task), f"{sha}:refs/heads/{branch}"],
                        cwd=git_for(task.repository).path,
                        env=github_git_env(self.settings),
                        timeout=300,
                    )
                except GitError as exc:
                    # the push may have landed before the connection dropped: reconcile
                    if client.get_branch_sha(full_name, branch) == sha:
                        return {"branch": branch, "sha": sha, "ref": branch, "reconciled": True}
                    raise PublishError(f"push failed: {exc}", retryable=True) from exc
                return {"branch": branch, "sha": sha, "ref": branch}

            _ledger(
                session,
                task,
                "push_branch",
                f"task:{task.id}:push:{branch}:{sha}",
                {"branch": branch, "sha": sha},
                push,
            )

            base = task.base_ref or task.repository.default_branch

            def create_pr(_: ExternalAction) -> dict[str, Any]:
                existing = client.find_pull_request(full_name, branch)
                if existing is not None:
                    return {"number": existing["number"], "url": existing["html_url"], "reconciled": True}
                try:
                    pr = client.create_pull_request(
                        full_name,
                        title=f"[modernisation] {task.title}",
                        body=self._pr_body(task),
                        head=branch,
                        base=base,
                        draft=True,
                    )
                except GitHubError as exc:
                    if exc.retryable or exc.status in (None, 422):
                        # timeout / 5xx / "already exists": the PR may exist now
                        existing = client.find_pull_request(full_name, branch)
                        if existing is not None:
                            return {"number": existing["number"], "url": existing["html_url"], "reconciled": True}
                    raise PublishError(f"pull request creation failed: {exc}", retryable=exc.retryable) from exc
                return {"number": pr["number"], "url": pr["html_url"]}

            pr = _ledger(
                session,
                task,
                "create_pull_request",
                f"task:{task.id}:pr:{branch}",
                {"head": branch, "base": base},
                create_pr,
            )
            task.pr_number = int(pr["number"])
            task.pr_url = str(pr["url"])
            session.commit()

            def report(_: ExternalAction) -> dict[str, Any]:
                client.create_status(
                    full_name,
                    sha,
                    state="success",
                    context="modernisation/verification",
                    description="Regression suite and static checks passed in an isolated sandbox",
                )
                return {"sha": sha, "ref": sha}

            try:
                _ledger(session, task, "report_status", f"task:{task.id}:status:{sha}", {"sha": sha}, report)
            except (GitHubError, PublishError) as exc:
                add_event(session, task.id, "error", f"could not report commit status: {exc}", state=task.state)
                session.commit()
            return {"kind": "github", "branch": branch, "sha": sha, "pr_number": task.pr_number, "pr_url": task.pr_url}
        except GitHubError as exc:
            raise PublishError(str(exc), retryable=exc.retryable) from exc
        finally:
            client.close()

    @staticmethod
    def _pr_body(task: Task) -> str:
        result = task.result or {}
        plan = task.plan or {}
        lines = [
            f"Automated maintenance change for task #{task.id} ({task.category}).",
            "",
            "**Request**",
            "",
            task.request[:3000],
            "",
            "**Plan summary**",
            "",
            str(plan.get("summary", "n/a"))[:2000],
            "",
            "**Verification (isolated sandbox, fresh checkout)**",
            "",
        ]
        for name, passed in (result.get("verification") or {}).items():
            lines.append(f"- {name}: {'passed' if passed else 'failed'}")
        lines += [
            "",
            f"Files changed: {', '.join(result.get('files_changed', []))}",
            "",
            "This pull request was opened as a draft and requires human review before merging.",
        ]
        return "\n".join(lines)
