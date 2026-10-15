"""The ``releasebot`` command line; ``--log``/``--tags`` are JSON exports from git, ``--json`` switches output."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import click

from releasebot import __version__
from releasebot.changelog import render_entry
from releasebot.commits import Commit
from releasebot.config import DEFAULT_FILENAME, ProjectConfig, load_config, update_version
from releasebot.errors import ReleasebotError
from releasebot.pep440 import check_publishable
from releasebot.plugins import PublishContext, available_publishers, get_publisher, publisher_origins
from releasebot.release import plan_release
from releasebot.tags import Tag
from releasebot.versioning import describe_version


def _complete_publishers(ctx: click.Context, args: list[str], incomplete: str) -> list[str]:
    """Shell completion for ``--publisher``."""
    return [name for name in sorted(available_publishers()) if name.startswith(incomplete)]


def command(func):
    """Register a sub-command whose :class:`ReleasebotError` is reported as a CLI error."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ReleasebotError as exc:
            raise click.ClickException(str(exc)) from exc

    return wrapper


def _echo(text: str) -> None:
    if not click.get_current_context().obj["json"]:
        click.echo(text)


def _config() -> ProjectConfig:
    return load_config(click.get_current_context().obj["config"])


def _read_list(path: str | None, factory: Any) -> list[Any]:
    if path is None:
        return []
    try:
        return [factory(item) for item in json.loads(Path(path).read_text(encoding="utf-8"))]
    except (ValueError, TypeError, KeyError) as exc:
        raise ReleasebotError(f"{path}: invalid JSON export ({exc})") from exc


def _plan(config: ProjectConfig, log: str, tags: str | None, prerelease: bool = False, required: bool = True) -> Any:
    log_, tags_ = _read_list(log, Commit.from_dict), _read_list(tags, Tag.from_dict)
    plan = plan_release(config, log_, tags_, prerelease=prerelease)
    if plan is None and required:
        raise ReleasebotError("no releasable changes since the last release")
    return plan


def history(func):
    func = click.option("--tags", type=click.Path(exists=True, dir_okay=False), help="Tags JSON export.")(func)
    return click.option("--log", type=click.Path(exists=True, dir_okay=False), required=True, help="Commit log.")(func)


@click.group()
@click.version_option(__version__, prog_name="releasebot")
@click.option("--config", "config_path", default=DEFAULT_FILENAME, show_default=True, help="Configuration file.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
@click.pass_context
def cli(ctx: click.Context, config_path: str, as_json: bool) -> None:
    """Release automation for Conventional Commits projects."""
    ctx.obj = {"config": Path(config_path), "json": as_json}


@cli.resultcallback()
def _emit_json(result: Any, config_path: str, as_json: bool) -> None:
    if as_json and result is not None:
        click.echo(json.dumps(result, indent=2, sort_keys=True))


@cli.command("next")
@history
@click.option("--pre", "prerelease", is_flag=True, help="Compute the next pre-release.")
@command
def next_command(log: str, tags: str | None, prerelease: bool) -> dict[str, Any]:
    """Print the next version."""
    plan = _plan(_config(), log, tags, prerelease, required=False)
    if plan is None:
        _echo("No release needed.")
        return {"release": False}
    _echo(plan.version)
    return {"release": True, **plan.to_dict(), "semver": describe_version(plan.version)}


@cli.command()
@history
@command
def changelog(log: str, tags: str | None) -> dict[str, Any]:
    """Print the changelog entry of the next release."""
    config = _config()
    plan = _plan(config, log, tags)
    entry = render_entry(plan, config)
    _echo(entry.rstrip("\n"))
    return {"version": plan.version, "changelog": entry}


@cli.command("check-index")
@history
@click.option("--published", type=click.Path(exists=True, dir_okay=False), required=True, help="Index versions.")
@command
def check_index(log: str, tags: str | None, published: str) -> dict[str, Any]:
    """Check that the next version can be uploaded to the package index."""
    plan = _plan(_config(), log, tags)
    pep440_version = check_publishable(plan.version, _read_list(published, str))
    _echo(f"{pep440_version} can be published")
    return {"version": plan.version, "pep440": pep440_version}


@cli.command()
@history
@click.option("--publisher", "names", multiple=True, autocompletion=_complete_publishers, help="Repeatable.")
@click.option("--dry-run", is_flag=True, help="Show what would be published.")
@click.option("--workdir", type=click.Path(file_okay=False), default=".", show_default=True)
@command
def publish(log: str, tags: str | None, names: tuple[str, ...], dry_run: bool, workdir: str) -> dict[str, Any]:
    """Publish the next release and record it as the last released version."""
    config = _config()
    plan = _plan(config, log, tags)
    context = PublishContext(Path(workdir), dry_run=dry_run)
    results: dict[str, str] = {}
    for name in names or config.publishers:
        publisher = get_publisher(name)(config)
        missing = publisher.missing_requirements()
        if missing:
            raise ReleasebotError(f"publisher {name!r} needs missing modules: {', '.join(missing)}")
        results[name] = publisher.publish(plan, context)
        _echo(f"{name}: {results[name]}")
    if not dry_run and not plan.prerelease and config.path is not None:
        update_version(config.path, plan.version)
    return {"version": plan.version, "dry_run": dry_run, "published": results}


@cli.command("publishers")
def list_publishers() -> dict[str, str]:
    """List available publishers, where they come from and what they do."""
    origins, publishers = publisher_origins(), available_publishers()
    width = click.get_terminal_size()[0]
    for name in sorted(origins):
        _echo(f"{name:<12} {origins[name]:<24} {publishers[name].description}"[:width].rstrip())
    return origins


def main() -> None:
    cli(prog_name="releasebot")
