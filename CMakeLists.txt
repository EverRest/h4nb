cmake_minimum_required(VERSION 3.24)
project(h4nb LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()
find_package(CUDAToolkit REQUIRED)
# Accuracy rule (TZ 4.4): never add --use_fast_math / -ffast-math. NaN checks rely on IEEE compares.

add_library(h4nb src/io.cpp src/kernels.cu src/simulation.cu)
target_include_directories(h4nb PUBLIC include PRIVATE src)

foreach(tool h4nb_run h4nb_mkdisk h4nb_bench h4nb_order)
  add_executable(${tool} tools/${tool}.cpp)
  target_include_directories(${tool} PRIVATE tools)
  target_link_libraries(${tool} PRIVATE h4nb)
endforeach()

# Tests. Label cpu: runs without a GPU. Label gpu: needs a CUDA device.
enable_testing()
function(h4nb_add_test name src label)
  add_executable(${name} ${src})
  target_include_directories(${name} PRIVATE src tools tests)
  target_link_libraries(${name} PRIVATE h4nb)
  add_test(NAME ${name} COMMAND ${name})
  set_tests_properties(${name} PROPERTIES LABELS ${label})
endfunction()

h4nb_add_test(test_math tests/test_math.cu cpu)
h4nb_add_test(test_io tests/test_io.cpp cpu)
h4nb_add_test(test_physics_cpu tests/test_physics_cpu.cu cpu)
h4nb_add_test(test_gpu_vs_ref tests/test_gpu_vs_ref.cu gpu)
h4nb_add_test(test_physics_gpu tests/test_physics_gpu.cu gpu)
h4nb_add_test(test_diagnostics tests/test_diagnostics.cu gpu)
# The two-body order check lives in the tool; run it here instead of duplicating it.
add_test(NAME h4nb_order COMMAND h4nb_order)
set_tests_properties(h4nb_order PROPERTIES LABELS gpu)
