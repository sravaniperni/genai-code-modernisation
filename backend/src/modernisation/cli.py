"""Command-line entry points: API server, worker, and maintenance utilities."""

from __future__ import annotations

import argparse
import json
import signal
import threading

from modernisation.config import get_settings
from modernisation.log import configure_logging
from modernisation.telemetry import configure_tracing


def build_worker():  # type: ignore[no-untyped-def]
    from modernisation.agents.worker import Worker
    from modernisation.agents.workflow import WorkflowEngine
    from modernisation.integrations.github.publisher import Publisher
    from modernisation.llm.factory import task_model_factory

    settings = get_settings()
    engine = WorkflowEngine(
        settings=settings, model_factory=task_model_factory(settings), publisher=Publisher(settings)
    )
    return Worker(engine, settings)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="modernisation")
    sub = parser.add_subparsers(dest="command", required=True)
    api = sub.add_parser("api", help="run the HTTP API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker", help="run a task worker")
    sub.add_parser("check-model", help="send one request to the configured model endpoint")
    reg = sub.add_parser("register-local", help="register a local git repository")
    reg.add_argument("name")
    reg.add_argument("path")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    configure_tracing(settings)

    if args.command == "api":
        import uvicorn

        from modernisation.api.app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, log_config=None)
    elif args.command == "worker":
        worker = build_worker()
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        worker.run_forever(stop)
    elif args.command == "check-model":
        from modernisation.llm.base import ChatMessage
        from modernisation.llm.factory import build_client

        client = build_client(settings)
        if client is None:
            raise SystemExit("no model configured (MODERNISATION_MODEL_PROVIDER / MODERNISATION_MODEL_NAME)")
        c = client.complete([ChatMessage("user", "Reply with the single word: ready")], purpose="health", max_tokens=5)
        print(
            json.dumps(
                {
                    "provider": c.provider,
                    "model": c.model,
                    "reply": c.text,
                    "latency_ms": c.latency_ms,
                    "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens,
                }
            )
        )
    elif args.command == "register-local":
        from modernisation.db.session import session_scope
        from modernisation.services.repositories import register_local

        with session_scope() as session:
            repo = register_local(session, args.name, args.path, settings)
            print(json.dumps({"id": repo.id, "name": repo.name, "default_branch": repo.default_branch}))


if __name__ == "__main__":
    main()
