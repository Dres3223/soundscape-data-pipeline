from soundscape.config import Settings
from soundscape.storage import s3_client

REQUIRED = {
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "pg-pass-7f3a",
    "POSTGRES_DB": "db",
    "S3_ACCESS_KEY": "key",
    "S3_SECRET_KEY": "s3-pass-9c1e",
}


def make_settings(monkeypatch, **env):
    for name, value in {**REQUIRED, **env}.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)  # ignore the developer's local .env


def test_endpoint_defaults_to_local_rustfs(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    assert make_settings(monkeypatch).s3_endpoint_url == "http://localhost:9000"


def test_empty_endpoint_means_aws_s3(monkeypatch):
    assert make_settings(monkeypatch, S3_ENDPOINT_URL="").s3_endpoint_url is None


def test_secrets_are_hidden_when_printed(monkeypatch):
    printed = repr(make_settings(monkeypatch))
    assert "pg-pass-7f3a" not in printed
    assert "s3-pass-9c1e" not in printed


def addressing_style(endpoint: str | None) -> str:
    settings = Settings(
        _env_file=None,
        postgres_user="u",
        postgres_password="p",
        postgres_db="d",
        s3_access_key="k",
        s3_secret_key="s",
        s3_endpoint_url=endpoint,
    )
    return s3_client(settings).meta.config.s3["addressing_style"]


def test_path_style_only_with_a_custom_endpoint():
    assert addressing_style("http://localhost:9000") == "path"
    assert addressing_style(None) == "auto"
