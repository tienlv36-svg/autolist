PY ?= .venv/bin/python
install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
install-browser:
	.venv/bin/pip install -e ".[browser]" && .venv/bin/playwright install chromium
install-ocr:
	sudo apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils && .venv/bin/pip install -e ".[ocr]"
test:
	.venv/bin/pytest -q
crawl:
	.venv/bin/auction crawl
export:
	.venv/bin/auction export
check:
	$(PY) tools/check_sources.py
