#----------------------------------------------------------------
# Generated CMake target import file for configuration "RelWithDebInfo".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "libaec::aec-shared" for configuration "RelWithDebInfo"
set_property(TARGET libaec::aec-shared APPEND PROPERTY IMPORTED_CONFIGURATIONS RELWITHDEBINFO)
set_target_properties(libaec::aec-shared PROPERTIES
  IMPORTED_LOCATION_RELWITHDEBINFO "${_IMPORT_PREFIX}/lib/libaec.0.1.6.dylib"
  IMPORTED_SONAME_RELWITHDEBINFO "@rpath/libaec.0.dylib"
  )

list(APPEND _cmake_import_check_targets libaec::aec-shared )
list(APPEND _cmake_import_check_files_for_libaec::aec-shared "${_IMPORT_PREFIX}/lib/libaec.0.1.6.dylib" )

# Import target "libaec::sz-shared" for configuration "RelWithDebInfo"
set_property(TARGET libaec::sz-shared APPEND PROPERTY IMPORTED_CONFIGURATIONS RELWITHDEBINFO)
set_target_properties(libaec::sz-shared PROPERTIES
  IMPORTED_LOCATION_RELWITHDEBINFO "${_IMPORT_PREFIX}/lib/libsz.2.0.1.dylib"
  IMPORTED_SONAME_RELWITHDEBINFO "@rpath/libsz.2.dylib"
  )

list(APPEND _cmake_import_check_targets libaec::sz-shared )
list(APPEND _cmake_import_check_files_for_libaec::sz-shared "${_IMPORT_PREFIX}/lib/libsz.2.0.1.dylib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
