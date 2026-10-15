"""camas task definitions for this project."""

from typing import Final

from camas import Claude, Config, Sequential, Task

format: Final = Task("uv run ruff format {paths}", mutates=True, paths=".")
format_check: Final = Task("uv run ruff format --check {paths}", paths=".")
lint: Final = Task("uv run ruff check {paths}", paths=".")
lint_fix: Final = Task("uv run ruff check --fix {paths}", mutates=True, paths=".")
fix: Final = lint_fix + format
mypy: Final = Task("uv run mypy src tests tasks.py")
pyright: Final = Task("uv run pyright")
typecheck: Final = mypy | pyright
test: Final = Task("uv run pytest")

check: Final = format_check | lint | typecheck | test
all: Final = Sequential(fix, typecheck | test)

_ = Config(default_task=all, github_task=check, agent=Claude(fix=fix, check=check))
