"""Keep the default suite CPU-only; optional model-stack tests are explicit."""
import importlib
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run tests requiring the configured InterGen stack and real CLIP tokenizer")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="Optional model-stack test; use --run-integration in the configured GPU environment")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def lodge():
    return importlib.import_module("LODGE_api.lodge_async_api")


@pytest.fixture
def intergen(tmp_path, monkeypatch):
    module = importlib.import_module("InterGen_api.intergen_async_api")
    monkeypatch.setattr(module, "DEFAULT_TASK_ROOT", tmp_path)
    monkeypatch.setattr(module, "_tasks", {})
    return module


@pytest.fixture
def task_root(tmp_path):
    return tmp_path
