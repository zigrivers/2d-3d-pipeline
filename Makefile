# 2d-3d-pipeline — docs and canonical script maintenance
#
# Usage:
#   make verify        check HTML embeds match /scripts and /skill
#   make regenerate    rewrite HTML embeds from canonical files
#   make bundle        zip canonical scripts + skill into dist/
#   make install-hooks point git at .githooks/
#   make clean         remove dist/

PYTHON ?= python3
GUIDE  := docs/asset-pipeline-guide.html
BUNDLE := dist/asset-pipeline-bundle.zip

.PHONY: help verify regenerate bundle install-hooks clean

help:
	@echo "Targets: verify regenerate bundle install-hooks clean"

verify:
	@$(PYTHON) tools/verify_embeds.py

regenerate:
	@$(PYTHON) tools/regenerate_embeds.py

bundle: $(BUNDLE)

$(BUNDLE): scripts/ skill/ $(GUIDE)
	@mkdir -p dist
	@rm -f $(BUNDLE)
	@zip -qr $(BUNDLE) scripts skill $(GUIDE)
	@echo "Wrote $(BUNDLE)"

install-hooks:
	@git config core.hooksPath .githooks
	@echo "Hooks installed: git will now run scripts in .githooks/"

clean:
	@rm -rf dist
