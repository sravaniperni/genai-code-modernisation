"""Built-in publishers."""

from __future__ import annotations

import os

from releasebot.changelog import prepend_entry, render_entry
from releasebot.errors import PublishError
from releasebot.hooks import run_hooks
from releasebot.notes import render_html, render_markdown
from releasebot.plugins import PublishContext, Publisher
from releasebot.release import ReleasePlan
from releasebot.staging import build_bundle


class ChangelogPublisher(Publisher):
    name = "changelog"
    description = "Prepend the release entry to the changelog file"

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        path = context.workdir / self.config.changelog.path
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not context.dry_run:
            path.write_text(prepend_entry(existing, render_entry(plan, self.config)), encoding="utf-8")
        return f"changelog entry for {plan.version} written to {path.name}"


class HostingPublisher(Publisher):
    name = "hosting"
    description = "Create a release on the code-hosting service"
    requires = ("httpx",)

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        from releasebot.hosting import HostingClient

        client = context.hosting_client or HostingClient.from_config(
            self.config.hosting, token=os.environ.get(self.config.hosting.token_env)
        )
        if client.get_release(plan.tag) is not None:
            raise PublishError(f"a release for {plan.tag} already exists")
        if context.dry_run:
            return f"would create release {plan.tag}"
        title = f"{self.config.project} {plan.version}"
        release = client.create_release(plan.tag, title, render_markdown(plan, self.config), prerelease=plan.prerelease)
        return f"created release {release.tag_name}"


class NotesPublisher(Publisher):
    name = "notes"
    description = "Write the release notes as a standalone HTML page"
    requires = ("markdown", "jinja2")

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        path = context.workdir / f"release-notes-{plan.version}.html"
        if not context.dry_run:
            path.write_text(render_html(plan, self.config), encoding="utf-8")
        return f"release notes written to {path.name}"


class HooksPublisher(Publisher):
    name = "hooks"
    description = "Run the shell commands configured under 'hooks'"

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        results = run_hooks(self.config.hooks, plan.variables(), cwd=context.workdir, runner=context.runner,
                            dry_run=context.dry_run)
        return f"ran {len(results)} hook(s)"


class BundlePublisher(Publisher):
    name = "bundle"
    description = "Pack changelog entry, notes and manifest into dist/<project>-<version>.tar.gz"

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        root = f"{self.config.project}-{plan.version}"
        destination = context.workdir / "dist" / f"{root}.tar.gz"
        if not context.dry_run:
            files = {"CHANGELOG.md": render_entry(plan, self.config), "release.json": plan.to_json(),
                     "RELEASE_NOTES.md": render_markdown(plan, self.config)}
            build_bundle(files, destination, root)
        return f"bundle written to dist/{destination.name}"


BUILTIN_PUBLISHERS = (ChangelogPublisher, HostingPublisher, NotesPublisher, HooksPublisher, BundlePublisher)
