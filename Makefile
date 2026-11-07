BUILD ?= build
# make pack RUN="run128k study" [OUT=a1.tar.gz] [SNAP=1]: pack the logs and results of runs into one archive.
RUN ?=
OUT ?=
SNAP ?= 0
.PHONY: build bench test pack
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
