.PHONY: install api test smoke report lint perf docker-test

install:
	pip install -r requirements-dev.txt

api:            ## run the API locally on http://localhost:8000 (docs at /docs)
	uvicorn app.main:app --reload

test:           ## full suite, starts its own API instance
	pytest -n auto

smoke:          ## fast gate
	pytest -m smoke

report:         ## HTML + JUnit reports in ./reports
	pytest -n auto --html=reports/report.html --self-contained-html --junitxml=reports/junit.xml

lint:
	ruff check .

perf:           ## needs k6 and a running API started with RATE_LIMIT_PER_MINUTE=1000000
	k6 run -e BASE_URL=http://localhost:8000 perf/transfers.js

docker-test:
	docker compose --profile test up --build --abort-on-container-exit --exit-code-from tests
