# Exercise the real startup path without letting any case access the GPU directly.
function(check_startup driver display wayland expected_status expected_message)
    execute_process(
        COMMAND "${CMAKE_COMMAND}" -E env
            "SDL_VIDEODRIVER=${driver}" "DISPLAY=${display}" "WAYLAND_DISPLAY=${wayland}"
            "${BLOB_OVERLAY}" --demo --frames 1
        RESULT_VARIABLE status OUTPUT_VARIABLE output ERROR_VARIABLE errors TIMEOUT 10)
    if(NOT "${status}" STREQUAL "${expected_status}" OR NOT "${errors}" MATCHES "${expected_message}")
        message(FATAL_ERROR "Unexpected startup for driver '${driver}', DISPLAY '${display}', WAYLAND_DISPLAY '${wayland}':\n${status}\n${output}\n${errors}")
    endif()
    if("${errors}" MATCHES "KMSDRM:")
        message(FATAL_ERROR "Startup probed the direct-display backend: ${errors}")
    endif()
endfunction()

check_startup("" "" "" 1 "Desktop display is not ready")
check_startup("kmsdrm" "" "" 1 "Unsupported SDL_VIDEODRIVER")
check_startup("x11,kmsdrm" "" "" 1 "Unsupported SDL_VIDEODRIVER")
check_startup("" "blob-invalid-display" "" 1 "Desktop video initialization failed \\(x11\\)")
check_startup("" "" "/nonexistent-projectblob-test/wayland" 1 "Desktop video initialization failed \\(wayland\\)")
check_startup("" "blob-invalid-display" "/nonexistent-projectblob-test/wayland" 1 "Desktop video initialization failed \\(x11\\)")
check_startup("dummy" "" "" 0 "Blob video driver: dummy")
