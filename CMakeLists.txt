cmake_minimum_required(VERSION 3.24)
project(h4nb VERSION 0.1.0 LANGUAGES CXX CUDA)

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
# A GPU-less build host (for example a login node) cannot use "native". Set the list there, for example "89;90".
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES native)
endif()
find_package(CUDAToolkit REQUIRED)
# Line tables for Nsight source view and compute-sanitizer. They do not change the generated code.
add_compile_options($<$<COMPILE_LANGUAGE:CUDA>:-lineinfo>)
# Warnings for all sources. CMAKE_CXX_FLAGS does not reach the .cu files, so the CUDA host compiler gets them here.
add_compile_options($<$<COMPILE_LANGUAGE:CXX>:-Wall> $<$<COMPILE_LANGUAGE:CXX>:-Wextra>
                    $<$<COMPILE_LANGUAGE:CUDA>:--compiler-options=-Wall,-Wextra>)
# Accuracy rule (TZ 4.4): never add --use_fast_math / -ffast-math. NaN checks rely on IEEE compares.

add_library(h4nb src/io.cpp src/diag_sum.cpp src/kernels.cu src/simulation.cu src/build_info.cu)
add_library(h4nb::h4nb ALIAS h4nb)
# The public header has no CUDA type, so CUDA::cudart is a private link.
target_link_libraries(h4nb PRIVATE CUDA::cudart)

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

# Build record for h4nb::build_info() (task T027). The header is written at every build, so a new commit is
# recorded at the next build. cmake/h4nb_build_stamp.cmake rewrites it only when the text changes.
set(H4NB_STAMP_DIR ${CMAKE_BINARY_DIR}/generated)
set(H4NB_STAMP_HEADER ${H4NB_STAMP_DIR}/h4nb_build_stamp.h)
# A build from a source archive has no Git data. Then the build record uses H4NB_SOURCE_VERSION (example: v0.1.0).
# The Spack recipe sets it for release versions.
set(H4NB_SOURCE_VERSION "" CACHE STRING "Source version for build_info() when Git cannot give the commit")
# A list of architectures (example: 80;90) becomes "80,90". A ';' separates the arguments of the script.
string(REPLACE ";" "," h4nb_archs "${CMAKE_CUDA_ARCHITECTURES}")
add_custom_target(h4nb_build_stamp
  COMMAND ${CMAKE_COMMAND} -DSRC_DIR=${CMAKE_SOURCE_DIR} -DOUT=${H4NB_STAMP_HEADER}
          -DH4NB_BUILD_TYPE=${CMAKE_BUILD_TYPE} -DH4NB_CUDA_ARCHITECTURES=${h4nb_archs}
          -DH4NB_SOURCE_VERSION=${H4NB_SOURCE_VERSION}
          -P ${CMAKE_SOURCE_DIR}/cmake/h4nb_build_stamp.cmake
  BYPRODUCTS ${H4NB_STAMP_HEADER}
  VERBATIM)
add_dependencies(h4nb h4nb_build_stamp)
target_include_directories(h4nb
  PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include> $<INSTALL_INTERFACE:include>
  PRIVATE src ${H4NB_STAMP_DIR})

foreach(tool h4nb_run h4nb_mkdisk h4nb_bench h4nb_order h4nb_study)
  add_executable(${tool} tools/${tool}.cpp)
  # run_info.hpp includes cuda_runtime.h and src/device_info.hpp (issue O9).
  target_include_directories(${tool} PRIVATE tools src)
  target_link_libraries(${tool} PRIVATE h4nb CUDA::cudart)
endforeach()

# Install rules (for "cmake --install" and for Spack, see docs/spack.md).
# The install puts the library, the public header, the tools and the example configs into the prefix.
include(GNUInstallDirs)
install(TARGETS h4nb EXPORT h4nbTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(TARGETS h4nb_run h4nb_mkdisk h4nb_bench h4nb_order h4nb_study
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(DIRECTORY configs/ DESTINATION ${CMAKE_INSTALL_DATADIR}/h4nb/configs)
# CMake package: find_package(h4nb) gives the target h4nb::h4nb.
include(CMakePackageConfigHelpers)
install(EXPORT h4nbTargets FILE h4nbTargets.cmake NAMESPACE h4nb:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/h4nb)
configure_package_config_file(${CMAKE_CURRENT_SOURCE_DIR}/cmake/h4nbConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/h4nbConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/h4nb)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/h4nbConfigVersion.cmake
  COMPATIBILITY SameMinorVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/h4nbConfig.cmake ${CMAKE_CURRENT_BINARY_DIR}/h4nbConfigVersion.cmake
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/h4nb)

# Tests. Label cpu: runs without a GPU. Label gpu: needs a CUDA device.
enable_testing()
function(h4nb_add_test name src label)
  add_executable(${name} ${src})
  target_include_directories(${name} PRIVATE src tools tests)
  target_link_libraries(${name} PRIVATE h4nb CUDA::cudart)
  add_test(NAME ${name} COMMAND ${name})
  set_tests_properties(${name} PROPERTIES LABELS ${label})
endfunction()

h4nb_add_test(test_math tests/test_math.cu cpu)
h4nb_add_test(test_io tests/test_io.cpp cpu)
h4nb_add_test(test_io_atomic tests/test_io_atomic.cpp cpu)
set_tests_properties(test_io_atomic PROPERTIES SKIP_RETURN_CODE 77)
h4nb_add_test(test_input tests/test_input.cpp cpu)
h4nb_add_test(test_settings tests/test_settings.cpp cpu)
h4nb_add_test(test_device_info tests/test_device_info.cpp cpu)
# h4nb_pack.sh test. Exit 77 when a tool is missing (for example GNU find on macOS).
add_test(NAME test_pack COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pack.sh ${CMAKE_CURRENT_SOURCE_DIR}/tools/h4nb_pack.sh)
set_tests_properties(test_pack PROPERTIES LABELS cpu SKIP_RETURN_CODE 77)
add_test(NAME exit_codes COMMAND sh ${CMAKE_CURRENT_SOURCE_DIR}/tests/exit_codes.sh $<TARGET_FILE:h4nb_run> $<TARGET_FILE:h4nb_study>)
set_tests_properties(exit_codes PROPERTIES LABELS cpu)
h4nb_add_test(test_metrics tests/test_metrics.cu cpu)
h4nb_add_test(test_mpi_staging tests/test_mpi_staging.cpp cpu)
h4nb_add_test(test_run_agree tests/test_run_agree.cpp cpu)
h4nb_add_test(test_diag_order tests/test_diag_order.cpp cpu)
h4nb_add_test(test_physics_cpu tests/test_physics_cpu.cu cpu)
h4nb_add_test(test_gpu_vs_ref tests/test_gpu_vs_ref.cu gpu)
h4nb_add_test(test_physics_gpu tests/test_physics_gpu.cu gpu)
h4nb_add_test(test_diagnostics tests/test_diagnostics.cu gpu)
h4nb_add_test(test_construct_leak tests/test_construct_leak.cu gpu)
# The two-body order check lives in the tool; run it here instead of duplicating it.
add_test(NAME h4nb_order COMMAND h4nb_order)
set_tests_properties(h4nb_order PROPERTIES LABELS gpu)
