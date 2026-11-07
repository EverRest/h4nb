cmake_minimum_required(VERSION 3.24)
project(h4nb LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
# GPU architectures. The default "native" builds for the GPUs of this machine. Examples:
#   cmake -S . -B build -DCMAKE_CUDA_ARCHITECTURES=89        # RTX 4070 Ti
#   cmake -S . -B build -DCMAKE_CUDA_ARCHITECTURES=90        # GH200 / H100
#   cmake -S . -B build -DCMAKE_CUDA_ARCHITECTURES="89;90"   # both
# The build sets no host-specific flag (no -march, no x86 intrinsics). So it also works on aarch64 (GH200).
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()
find_package(CUDAToolkit REQUIRED)
# Accuracy rule (TZ 4.4): never add --use_fast_math / -ffast-math. NaN checks rely on IEEE compares.

add_library(h4nb src/io.cpp src/kernels.cu src/simulation.cu src/build_info.cu)

# Optional MPI path (tasks T029 to T036, docs/multi-node-design.md). Default OFF: the build then has no MPI dependency.
# With ON, src/mpi_comm.cpp holds all MPI calls. Only that file includes mpi.h. simulation.cu calls it through the
# MPI-free header src/mpi_comm.hpp. Without MPI, src/single_rank.cpp gives the same public functions for one rank.
option(H4NB_MPI "Build the MPI path (one rank per GPU, several nodes)" OFF)
if(H4NB_MPI)
  find_package(MPI REQUIRED COMPONENTS CXX)
  target_sources(h4nb PRIVATE src/mpi_comm.cpp)
  set_source_files_properties(src/mpi_comm.cpp PROPERTIES COMPILE_DEFINITIONS "OMPI_SKIP_MPICXX=1;MPICH_SKIP_MPICXX=1")
  set_property(SOURCE src/simulation.cu src/mpi_comm.cpp src/build_info.cu APPEND PROPERTY COMPILE_DEFINITIONS H4NB_HAVE_MPI=1)
  target_link_libraries(h4nb PRIVATE MPI::MPI_CXX)
else()
  target_sources(h4nb PRIVATE src/single_rank.cpp)
endif()

# Build record for h4nb::build_info() (task T027). CMake reads the commit at configure time.
# A later commit does not change the value until the next configure step.
set(H4NB_GIT_COMMIT "unknown")
find_package(Git QUIET)
if(GIT_FOUND)
  execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse --short HEAD WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
                  OUTPUT_VARIABLE h4nb_commit OUTPUT_STRIP_TRAILING_WHITESPACE RESULT_VARIABLE h4nb_git_rc ERROR_QUIET)
  if(h4nb_git_rc EQUAL 0 AND h4nb_commit)
    set(H4NB_GIT_COMMIT "${h4nb_commit}")
    execute_process(COMMAND ${GIT_EXECUTABLE} status --porcelain WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
                    OUTPUT_VARIABLE h4nb_git_status OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    if(h4nb_git_status)
      string(APPEND H4NB_GIT_COMMIT "-dirty")
    endif()
  endif()
endif()
# A list of architectures (example: 80;90) becomes "80,90". A ';' separates the definitions.
string(REPLACE ";" "," h4nb_archs "${CMAKE_CUDA_ARCHITECTURES}")
set_property(SOURCE src/build_info.cu APPEND PROPERTY COMPILE_DEFINITIONS
  "H4NB_GIT_COMMIT=\"${H4NB_GIT_COMMIT}\";H4NB_BUILD_TYPE=\"${CMAKE_BUILD_TYPE}\";H4NB_CUDA_ARCHITECTURES=\"${h4nb_archs}\"")
target_include_directories(h4nb PUBLIC include PRIVATE src)

foreach(tool h4nb_run h4nb_mkdisk h4nb_bench h4nb_order h4nb_study)
  add_executable(${tool} tools/${tool}.cpp)
  # run_info.hpp includes cuda_runtime.h. The h4nb library already links the CUDA runtime.
  target_include_directories(${tool} PRIVATE tools ${CUDAToolkit_INCLUDE_DIRS})
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
h4nb_add_test(test_io_atomic tests/test_io_atomic.cpp cpu)
h4nb_add_test(test_input tests/test_input.cpp cpu)
add_test(NAME exit_codes COMMAND sh ${CMAKE_CURRENT_SOURCE_DIR}/tests/exit_codes.sh $<TARGET_FILE:h4nb_run> $<TARGET_FILE:h4nb_study>)
set_tests_properties(exit_codes PROPERTIES LABELS cpu)
h4nb_add_test(test_metrics tests/test_metrics.cu cpu)
h4nb_add_test(test_mpi_staging tests/test_mpi_staging.cpp cpu)
h4nb_add_test(test_run_agree tests/test_run_agree.cpp cpu)
h4nb_add_test(test_physics_cpu tests/test_physics_cpu.cu cpu)
h4nb_add_test(test_gpu_vs_ref tests/test_gpu_vs_ref.cu gpu)
h4nb_add_test(test_physics_gpu tests/test_physics_gpu.cu gpu)
h4nb_add_test(test_diagnostics tests/test_diagnostics.cu gpu)
h4nb_add_test(test_construct_leak tests/test_construct_leak.cu gpu)
# The two-body order check lives in the tool; run it here instead of duplicating it.
add_test(NAME h4nb_order COMMAND h4nb_order)
set_tests_properties(h4nb_order PROPERTIES LABELS gpu)
