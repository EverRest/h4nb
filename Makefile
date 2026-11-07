BUILD ?= build
# make pack RUN="run128k study" [OUT=a1.tar.gz] [SNAP=1]: pack the logs and results of runs into one archive.
RUN ?=
OUT ?=
SNAP ?= 0
# make release VERSION=0.1.0: make the tag v0.1.0 (no push). After you push the tag:
# make release-recipe VERSION=0.1.0: add the version to the Spack recipe and commit it (no push). See docs/spack.md.
VERSION ?=
.PHONY: build bench test pack release release-recipe
build:
	cmake -S . -B $(BUILD) -DCMAKE_BUILD_TYPE=Release
	cmake --build $(BUILD) -j
bench: build
	$(BUILD)/h4nb_bench
test: build
	ctest --test-dir $(BUILD) --output-on-failure
pack:
	@test -n "$(RUN)" || { echo 'make pack: set RUN, for example: make pack RUN="run128k study"' >&2; exit 2; }
	tools/h4nb_pack.sh $(if $(OUT),-o "$(OUT)") $(if $(filter 1,$(SNAP)),--snap) $(RUN)
release:
	@test -n "$(VERSION)" || { echo 'make release: set VERSION, for example: make release VERSION=0.1.0' >&2; exit 2; }
	tools/h4nb_release.sh tag "$(VERSION)"
release-recipe:
	@test -n "$(VERSION)" || { echo 'make release-recipe: set VERSION, for example: make release-recipe VERSION=0.1.0' >&2; exit 2; }
	tools/h4nb_release.sh recipe "$(VERSION)"
