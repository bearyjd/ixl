.PHONY: setup test lint

setup:
	git config core.hooksPath .githooks
	chmod +x .githooks/post-commit scripts/bump-version.sh
	@echo "Git hooks installed. Version will auto-bump on feat:/fix: commits."

test:
	python3 -m pytest

lint:
	ruff check ixl_cli/
