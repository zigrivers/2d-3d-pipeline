# 2d-3d-pipeline — docs and canonical script maintenance
#
# Usage:
#   make verify        check HTML embeds match /scripts and /skill
#   make regenerate    rewrite HTML embeds from canonical files
#   make bundle        zip canonical scripts + skill into dist/
#   make install-hooks point git at .githooks/
#   make clean         remove dist/

PYTHON ?= python3
# Use pyenv Python for pytest (homebrew python@3.12 has broken pyexpat on this host)
PYTEST_PYTHON ?= $(HOME)/.pyenv/versions/3.12.3/bin/python3.12
GUIDE  := docs/asset-pipeline-guide.html
GUIDE_STUDIO := docs/asset-pipeline-guide-studio.html
BUNDLE := dist/asset-pipeline-bundle.zip

.PHONY: help verify regenerate bundle install-hooks clean test

help:
	@echo "Targets: verify regenerate bundle install-hooks clean test"

verify:
	@$(PYTHON) tools/verify_embeds.py
	@$(PYTHON) tools/check_context_parity.py

regenerate:
	@$(PYTHON) tools/regenerate_embeds.py

bundle: $(BUNDLE)

# Bundle: canonical scripts + skill + both setup guides + UPGRADES + the
# docs landing page. Excludes __pycache__ and ephemeral planning files so
# the bundle stays clean for distribution.
$(BUNDLE): scripts/ skill/ $(GUIDE) $(GUIDE_STUDIO)
	@mkdir -p dist
	@rm -f $(BUNDLE)
	@zip -qr $(BUNDLE) scripts skill $(GUIDE) $(GUIDE_STUDIO) \
	    docs/UPGRADES-laptop.md docs/UPGRADES-studio.md docs/index.html \
	    -x '*/__pycache__/*' '*.pyc' 'scripts/__pycache__' 'skill/scripts/__pycache__'
	@echo "Wrote $(BUNDLE)"

install-hooks:
	@git config core.hooksPath .githooks
	@echo "Hooks installed: git will now run scripts in .githooks/"

clean:
	@rm -rf dist

test:
	./tools/test_meta_helper.sh
	./tools/test_update_manifest_meta.sh
	$(PYTEST_PYTHON) -m pytest tests/python -v
