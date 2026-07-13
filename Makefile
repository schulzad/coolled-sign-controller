.PHONY: install install-api test preview scan clean

install:
	python -m pip install -e .

install-api:
	python -m pip install -e '.[api]'

test:
	PYTHONPATH=src python -m pytest

preview:
	PYTHONPATH=src python -m opensign.animation.preview --pattern two-frame --output examples/generated/two-frame.gif --bundle-out examples/generated/two-frame.bundle.json

scan:
	PYTHONPATH=src python -m opensign.hardware_probe.cli scan --timeout 10 --output evidence/advertisements/latest.json

clean:
	rm -rf build dist .pytest_cache .ruff_cache src/*.egg-info src/opensign_coolled.egg-info
