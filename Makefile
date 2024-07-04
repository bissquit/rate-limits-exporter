env:
	mkdir -p venv
	python3 -m venv venv
	pip3 install tox

test:
	tox -v

start:
	docker-compose up -d --build

stop:
	docker-compose down
