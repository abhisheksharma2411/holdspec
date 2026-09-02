# HoldSpec -- formal model and conformance suite for the PSP hold lifecycle.
#
#   make setup        create the virtualenv and fetch tla2tools.jar
#   make check        model-check every provider profile
#   make test         unit and sanity tests
#   make experiments  run E1-E6 and write results/
#   make figures      regenerate figures from results/
#   make paper        build paper/holdspec.pdf
#   make reproduce    all of the above, from a clean tree

PY       := .venv/bin/python
PIP      := .venv/bin/pip
TLA_JAR  := tools/tla2tools.jar
TLA_URL  := https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar

.PHONY: setup check test experiments figures paper reproduce clean data services

setup: $(PY) $(TLA_JAR)

$(PY):
	python3 -m venv .venv
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt

$(TLA_JAR):
	mkdir -p tools
	curl -sSL -o $(TLA_JAR) $(TLA_URL)

# There is no dataset to build: the profiles are read from public provider
# documentation and the workloads are generated from the model. This target
# regenerates the TLC configuration files from src/holdspec/profiles.py.
data: setup
	$(PY) -c "import sys; sys.path.insert(0,'src'); \
	from pathlib import Path; from holdspec.profiles import ALL_PROFILES; \
	from holdspec.tlc import write_config; \
	[write_config(p, Path('spec/profiles')/(p.name+'.cfg')) for p in ALL_PROFILES]; \
	print('wrote', len(ALL_PROFILES), 'TLC configurations')"

check: setup data
	$(PY) experiments/e1_model_check.py

test: setup
	$(PY) -m pytest

experiments: setup data
	$(PY) experiments/run_all.py

figures: setup
	$(PY) figures/make_figures.py

# Tables and in-prose numbers are generated from results/ first, so the PDF can
# never contain a hand-entered number.
paper: setup
	$(PY) paper/make_tables.py
	cd paper && latexmk -pdf -interaction=nonstopmode -halt-on-error holdspec.tex

# Optional: Postgres for the run log plus a mock PSP per API shape. The
# experiments run without this; they fall back to SQLite and subprocesses.
services:
	docker compose up -d --wait

reproduce: clean setup data test experiments figures paper
	@echo
	@echo "reproduction complete: results/ figures/ paper/holdspec.pdf"

clean:
	rm -rf results/*.json results/*.log results/tlc_dumps results/holdspec.sqlite \
	       spec/states spec/profiles/*.cfg spec/HoldSpecS*.tla \
	       figures/*.pdf figures/*.png paper/tables/*.tex \
	       paper/*.aux paper/*.log paper/*.out paper/*.fls paper/*.fdb_latexmk \
	       paper/*.bbl paper/*.blg paper/holdspec.pdf
