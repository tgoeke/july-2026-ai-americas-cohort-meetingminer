# Thin delegate — all logic lives in infra/Makefile (story 1.1).
# The catch-all forwards ANY target so this file never drifts from infra/.

.DEFAULT_GOAL := help
.PHONY: FORCE

# Never try to remake this Makefile via the catch-all.
Makefile: ;

# FORCE keeps existing files/dirs (web, docs, ...) from short-circuiting
# the delegation as "already up to date".
%: FORCE
	@$(MAKE) -C infra $@

FORCE: ;
