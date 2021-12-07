env:
	mkdir venv || true
	@echo Create Python virtual environment
	python3 -m venv venv
	@echo "Run manually the command below to activate Python venv in your current shell environment:\n\n. venv/bin/activate"

test:
	@echo Instal project requirements
	pip install -r requirements.txt
	@echo Instal modules
	pip install -e .

	@echo Check PEP8 conformity
	flake8 src/* \
		--show-source \
		--max-line-length 175
	@echo Run tests
	pytest -vvv
	@echo Check test coverage
	coverage erase
	coverage run --source=./src --rcfile=.coveragerc -m pytest
	coverage report
	coverage html

run:
	python3 src/rate_limits_exporter.py
