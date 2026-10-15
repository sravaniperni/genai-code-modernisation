import logging

import pytest
from conftest import make_config

from webhookrelay.config import ConfigError, load_config


def test_load_config():
    config = load_config(make_config(plugins=["tagger"]))
    assert set(config.sources) == {"acme", "plain"}
    assert config.sources["acme"].tolerance == 300
    audit = config.targets["audit"]
    assert (audit.auth, audit.transport, audit.template) == ("hmac", "httpx", None)
    assert config.targets["chat"].auth == "none"
    assert [r.name for r in config.rules] == ["orders", "everything"]
    assert config.retry.max_attempts == 3
    assert config.retry_policy_for(audit).max_attempts == 3
    assert config.plugins == ["tagger"]


def test_unknown_keys_are_reported(caplog):
    with caplog.at_level(logging.WARNING):
        load_config(make_config(retries=5, colour="blue"))
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert messages == ["ignoring unknown configuration key 'colour'", "ignoring unknown configuration key 'retries'"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"rules": [{"targets": ["nowhere"]}]}, "unknown target"),
        ({"targets": {"x": {"url": "https://x.example", "auth": "jwt"}}}, "needs a secret"),
        ({"targets": {"x": {"secret": "s"}}}, "no url"),
        ({"retry": {"attempts": 3}}, "unknown retry setting"),
    ],
)
def test_invalid_configuration(overrides, message):
    with pytest.raises(ConfigError, match=message):
        load_config(make_config(**overrides))
