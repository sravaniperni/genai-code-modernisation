"""HTTP API tests against real PostgreSQL and git repositories."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modernisation.config import reset_settings_cache
from tests.helpers import BUG_REQUEST

pytestmark = pytest.mark.postgres


@pytest.fixture()
def api(db: None) -> Iterator[TestClient]:
    reset_settings_cache()
    from modernisation.api.app import create_app

    yield TestClient(create_app())


@pytest.fixture()
def repo_id(api: TestClient, sample_repo: Path) -> int:
    r = api.post("/api/repositories", json={"kind": "local", "source": str(sample_repo), "name": "inventory"})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_health_and_meta(api: TestClient):
    health = api.get("/api/health").json()
    assert health["database"] is True and health["model_configured"] is False
    meta = api.get("/api/meta").json()
    assert "AWAITING_APPROVAL" in meta["states"] and "dependency_upgrade" in meta["categories"]


def test_repository_registration_authorisation(api: TestClient, tmp_path: Path):
    r = api.post("/api/repositories", json={"kind": "local", "source": str(tmp_path)})
    assert r.status_code == 403
    r = api.post("/api/repositories", json={"kind": "github", "source": "someone-else/private-repo"})
    assert r.status_code == 403
    r = api.post("/api/repositories", json={"kind": "github", "source": "../../etc"})
    assert r.status_code == 403


def test_repository_explorer_endpoints(api: TestClient, repo_id: int):
    repos = api.get("/api/repositories").json()
    assert repos[0]["name"] == "inventory" and repos[0]["default_branch"] == "main"
    snap = api.post(f"/api/repositories/{repo_id}/index", json={}).json()
    assert snap["status"] == "ready" and snap["files_total"] == 8
    tree = api.get(f"/api/repositories/{repo_id}/tree").json()
    paths = {f["path"]: f for f in tree["files"]}
    assert paths["tests/test_pricing.py"]["is_test"] and paths["pyproject.toml"]["is_config"]
    f = api.get(f"/api/repositories/{repo_id}/file", params={"path": "src/inventory/pricing.py"}).json()
    assert f["commit_sha"] == snap["commit_sha"] and any(s["name"] == "apply_discount" for s in f["symbols"])
    assert api.get(f"/api/repositories/{repo_id}/file", params={"path": "nope.py"}).status_code == 404

    text = api.get(f"/api/repositories/{repo_id}/search", params={"q": "percent / 1000"}).json()
    assert text["results"][0]["path"] == "src/inventory/pricing.py" and text["results"][0]["start_line"] == 14
    regex = api.get(f"/api/repositories/{repo_id}/search", params={"q": r"def \w+_total", "mode": "regex"}).json()
    assert regex["results"][0]["symbol"] == "order_total"
    bad = api.get(f"/api/repositories/{repo_id}/search", params={"q": "(", "mode": "regex"})
    assert bad.status_code == 400
    syms = api.get(f"/api/repositories/{repo_id}/search", params={"q": "LineItem", "mode": "symbol"}).json()
    assert syms["results"][0]["kind"] == "class"
    refs = api.get(f"/api/repositories/{repo_id}/search", params={"q": "is_bulk", "mode": "references"}).json()
    assert {r["path"] for r in refs["results"]} == {"src/inventory/report.py"}

    retrieved = api.post(f"/api/repositories/{repo_id}/retrieve", json={"request": BUG_REQUEST, "category": "bug_fix"})
    top = retrieved.json()["references"][0]
    assert top["path"] == "src/inventory/pricing.py" and top["commit_sha"] == snap["commit_sha"]
    impact = api.post(f"/api/repositories/{repo_id}/impact", json={"paths": ["src/inventory/models.py"]}).json()
    assert "src/inventory/pricing.py" in {d["path"] for d in impact["dependents"]}

    commits = api.get(f"/api/repositories/{repo_id}/commits").json()
    assert commits[0]["subject"] == "initial import"
    assert "main" in api.get(f"/api/repositories/{repo_id}/branches").json()
    assert api.get(f"/api/repositories/{repo_id}/commits", params={"ref": "--all"}).status_code == 400


def test_task_lifecycle_endpoints(api: TestClient, repo_id: int):
    body = {
        "repository_id": repo_id,
        "title": "Fix discount",
        "request": BUG_REQUEST,
        "category": "bug_fix",
        "allowed_paths": ["src/**"],
        "config": {"max_attempts": 2},
    }
    created = api.post("/api/tasks", json=body)
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["state"] == "QUEUED"
    detail = api.get(f"/api/tasks/{task['id']}").json()
    assert len(detail["base_commit"]) == 40 and detail["usage"]["model_calls"] == 0
    events = api.get(f"/api/tasks/{task['id']}/events").json()
    assert events[0]["message"].startswith("task created")

    # approvals are refused unless the task is waiting for that stage
    r = api.post(
        f"/api/tasks/{task['id']}/approval",
        json={"stage": "publish", "decision": "approved", "reviewer": "x", "expected_version": task["version"]},
    )
    assert r.status_code == 409
    assert api.post(f"/api/tasks/{task['id']}/cancel").json()["state"] == "CANCELLED"
    assert api.post(f"/api/tasks/{task['id']}/cancel").status_code == 409
    assert api.post(f"/api/tasks/{task['id']}/restart").json()["state"] == "QUEUED"
    listed = api.get("/api/tasks", params={"state": "queued"}).json()
    assert [t["id"] for t in listed] == [task["id"]]
    dash = api.get("/api/dashboard").json()
    assert dash["repositories"] == 1 and dash["tasks_by_state"] == {"QUEUED": 1}


@pytest.mark.parametrize("scope", [["../secrets"], ["/etc/**"], ["src/../../x"]])
def test_task_scope_validation(api: TestClient, repo_id: int, scope: list[str]):
    body = {
        "repository_id": repo_id,
        "title": "x" * 5,
        "request": "y" * 20,
        "category": "bug_fix",
        "allowed_paths": scope,
    }
    assert api.post("/api/tasks", json=body).status_code == 422


def test_unknown_ref_and_category_rejected(api: TestClient, repo_id: int):
    base = {"repository_id": repo_id, "title": "xxxxx", "request": "y" * 20}
    assert api.post("/api/tasks", json={**base, "category": "rewrite_everything"}).status_code == 422
    assert api.post("/api/tasks", json={**base, "category": "bug_fix", "base_ref": "no-such-branch"}).status_code == 400


def test_settings_never_expose_secrets(db: None, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODERNISATION_MODEL_API_KEY", "model-secret-value-xyz")
    monkeypatch.setenv("MODERNISATION_GITHUB_TOKEN", "gh-secret-value-xyz")
    reset_settings_cache()
    from modernisation.api.app import create_app

    body = TestClient(create_app()).get("/api/settings").text
    assert "secret-value" not in body
    assert '"api_key_configured":true' in body.replace(" ", "")
    reset_settings_cache()


def test_api_token_enforced_on_mutations(db: None, monkeypatch: pytest.MonkeyPatch, sample_repo: Path):
    monkeypatch.setenv("MODERNISATION_API_TOKEN", "local-api-token")
    reset_settings_cache()
    from modernisation.api.app import create_app

    client = TestClient(create_app())
    body = {"kind": "local", "source": str(sample_repo)}
    assert client.post("/api/repositories", json=body).status_code == 401
    assert client.post("/api/repositories", json=body, headers={"authorization": "Bearer wrong"}).status_code == 401
    ok = client.post("/api/repositories", json=body, headers={"authorization": "Bearer local-api-token"})
    assert ok.status_code == 201
    assert client.get("/api/repositories").status_code == 200  # reads stay open
    reset_settings_cache()


def test_evaluation_endpoints_report_absence_honestly(api: TestClient):
    assert api.get("/api/evaluation/runs").json() == []
    assert api.get("/api/evaluation/runs/1").status_code == 404


def test_model_test_endpoint_without_model(api: TestClient):
    assert api.post("/api/settings/model/test").status_code == 400


def test_read_endpoints_never_index_implicitly(api: TestClient, repo_id: int):
    for path in ("tree", "search?q=x", "file?path=README.md"):
        r = api.get(f"/api/repositories/{repo_id}/{path}")
        assert r.status_code == 409 and "POST /index first" in r.json()["detail"]
    assert api.get(f"/api/repositories/{repo_id}/snapshots").json() == []
    api.post(f"/api/repositories/{repo_id}/index", json={})
    assert api.get(f"/api/repositories/{repo_id}/tree").status_code == 200
    assert api.get(f"/api/repositories/{repo_id}/tree", params={"ref": "no-such-ref"}).status_code == 400


def test_meta_and_not_found_contracts(api: TestClient):
    meta = api.get("/api/meta").json()
    assert set(meta["terminal_states"]) == {"COMPLETED", "FAILED", "CANCELLED", "ESCALATED"}
    assert "QUEUED" in meta["runnable_states"] and meta["restartable_states"] == ["CANCELLED", "ESCALATED", "FAILED"]
    assert api.get("/api/tasks/999/model-calls").status_code == 404
    assert api.get("/api/health").json()["active_workers"] == []
