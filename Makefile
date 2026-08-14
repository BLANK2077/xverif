.PHONY: all xdebug xbit xentry xloc xcov xwaveform clean install-all-skill remove-legacy-xverif-skills install-xverif-skill install-xverif-admin-skill install-xwiki-skill install-x-npi-skill install-xsimdebug-skill _install-agent-skill

PYTHON ?= python3

all: xdebug xbit xentry xloc xcov xwaveform

xdebug:
	$(MAKE) -C xdebug

xbit:
	$(MAKE) -C xbit

xentry:
	$(MAKE) -C xentry

xloc:
	$(MAKE) -C xloc

xcov:
	@true

xwaveform:
	$(MAKE) -C xwaveform

install-xverif-skill:
	$(MAKE) _install-agent-skill SKILL_SRC=skills/xverif SKILL_NAME=xverif

install-xverif-admin-skill:
	$(MAKE) _install-agent-skill SKILL_SRC=skills/xverif-admin SKILL_NAME=xverif-admin

install-xwiki-skill:
	$(MAKE) _install-agent-skill SKILL_SRC=skills/xwiki SKILL_NAME=xwiki

install-x-npi-skill:
	$(MAKE) _install-agent-skill SKILL_SRC=skills/x-npi SKILL_NAME=x-npi

install-xsimdebug-skill:
	$(MAKE) _install-agent-skill SKILL_SRC=skills/xsimdebug SKILL_NAME=xsimdebug

remove-legacy-xverif-skills:
	@set -eu; \
	for home in "$$HOME/.codex" "$$HOME/.claude"; do \
		for legacy in xverif-cli xverif-mcp; do \
			dst="$$home/skills/$$legacy"; \
			if [ -e "$$dst" ]; then \
				echo "==> Removing retired skill $$dst"; \
				rm -rf "$$dst"; \
			fi; \
		done; \
	done

install-all-skill: remove-legacy-xverif-skills
	@set -eu; \
	found=0; \
	for skill_md in skills/*/SKILL.md; do \
		if [ ! -e "$$skill_md" ]; then \
			continue; \
		fi; \
		found=1; \
		src=$$(dirname "$$skill_md"); \
		name=$$(basename "$$src"); \
		$(MAKE) _install-agent-skill SKILL_SRC="$$src" SKILL_NAME="$$name"; \
	done; \
	if [ "$$found" -eq 0 ]; then \
		echo "ERROR: no skills/*/SKILL.md found"; \
		exit 1; \
	fi

_install-agent-skill:
	@set -eu; \
	src="$(SKILL_SRC)"; \
	name="$(SKILL_NAME)"; \
	ts=$$(date +%Y%m%d-%H%M%S); \
	if [ ! -f "$$src/SKILL.md" ]; then \
		echo "ERROR: missing $$src/SKILL.md"; \
		exit 1; \
	fi; \
	for home in "$$HOME/.codex" "$$HOME/.claude"; do \
		skills_dir="$$home/skills"; \
		dst="$$skills_dir/$$name"; \
		bak="$$home/$$name-skill.bak.$$ts"; \
		echo "==> Installing $$name skill into $$dst"; \
		mkdir -p "$$skills_dir"; \
		if [ -e "$$dst" ]; then \
			echo "    existing skill found: $$dst"; \
			echo "    moving existing skill to backup outside skills dir: $$bak"; \
			mv "$$dst" "$$bak"; \
		else \
			echo "    no existing $$name skill found in $$skills_dir"; \
		fi; \
		echo "    syncing $$src -> $$dst"; \
		rsync -a --delete --exclude '__pycache__/' --exclude '*.py[cod]' --exclude '.pytest_cache/' "$$src/" "$$dst/"; \
		printf 'source=%s\ncommit=%s\n' "$$src" "$$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" > "$$dst/.xverif-skill-manifest"; \
		diff -qr --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' --exclude '.xverif-skill-manifest' "$$src" "$$dst"; \
		echo "    installed and verified $$name skill at $$dst"; \
	done; \
	echo "Done. Backups, if any, were moved to ~/.codex/ or ~/.claude/ so agents do not load old and new skills twice."

clean:
	$(MAKE) -C xdebug clean
	$(MAKE) -C xbit clean
	$(MAKE) -C xentry clean
	$(MAKE) -C xloc clean
	$(MAKE) -C xwaveform clean
