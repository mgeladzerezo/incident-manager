from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.db import Base, make_engine


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.cmd_opts = type("Options", (), {"x": [f"url={url}"]})()
    return config


def test_migrations_produce_the_schema_the_models_describe(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")

    engine = make_engine(url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()

    assert differences == []


def test_downgrade_removes_everything(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = make_engine(url)
    tables = inspect(engine).get_table_names()
    engine.dispose()

    assert tables == ["alembic_version"]
