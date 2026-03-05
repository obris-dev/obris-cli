.PHONY: publish

publish:
	rm -rf dist/
	uv build
	@UV_PUBLISH_PASSWORD=$(OBRIS_CLI_PYPI_TOKEN) uv publish