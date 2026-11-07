# Writes the build record header. CMake runs this script at every build (cmake -P).
# configure_file() does not touch the output when the text is the same, so a build without changes compiles nothing.
# Inputs (-D): SRC_DIR (git work tree), OUT (header path), H4NB_BUILD_TYPE, H4NB_CUDA_ARCHITECTURES (comma list),
# H4NB_SOURCE_VERSION (used when Git cannot give the commit, for example a build from a release archive).
set(H4NB_GIT_COMMIT "unknown")
find_package(Git QUIET)
if(GIT_FOUND)
  execute_process(COMMAND ${GIT_EXECUTABLE} rev-parse --short HEAD WORKING_DIRECTORY ${SRC_DIR}
                  OUTPUT_VARIABLE h4nb_commit OUTPUT_STRIP_TRAILING_WHITESPACE RESULT_VARIABLE h4nb_git_rc ERROR_QUIET)
  if(h4nb_git_rc EQUAL 0 AND h4nb_commit)
    set(H4NB_GIT_COMMIT "${h4nb_commit}")
    # Untracked files are not counted. Build directories are untracked and would mark every build as -dirty.
    execute_process(COMMAND ${GIT_EXECUTABLE} status --porcelain --untracked-files=no WORKING_DIRECTORY ${SRC_DIR}
                    OUTPUT_VARIABLE h4nb_git_status OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    if(h4nb_git_status)
      string(APPEND H4NB_GIT_COMMIT "-dirty")
    endif()
  endif()
endif()
# A build from a source archive has no Git data. Then the source version (example: v0.1.0) is the record.
if(H4NB_GIT_COMMIT STREQUAL "unknown" AND H4NB_SOURCE_VERSION)
  set(H4NB_GIT_COMMIT "${H4NB_SOURCE_VERSION}")
endif()
configure_file(${CMAKE_CURRENT_LIST_DIR}/h4nb_build_stamp.h.in ${OUT} @ONLY)
