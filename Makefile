BUILD ?= build
.PHONY: build bench test
build:
	cmake -S . -B $(BUILD) -DCMAKE_BUILD_TYPE=Release
	cmake --build $(BUILD) -j
bench: build
	$(BUILD)/h4nb_bench
test: build
	ctest --test-dir $(BUILD) --output-on-failure
