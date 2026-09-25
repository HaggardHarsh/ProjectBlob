cmake_minimum_required(VERSION 3.15)
project(blob_frontend CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ─── Find Dependencies ───
find_package(SDL2 REQUIRED CONFIG)
find_package(OpenGL REQUIRED)
find_package(gRPC CONFIG REQUIRED)

# GLEW - try config mode first, then manual
find_path(GLEW_INCLUDE_DIR GL/glew.h)
find_library(GLEW_LIBRARY NAMES GLEW glew)

if(NOT GLEW_INCLUDE_DIR OR NOT GLEW_LIBRARY)
    message(WARNING "GLEW not found - building without GLEW (some features may be limited)")
    set(HAS_GLEW OFF)
else()
    set(HAS_GLEW ON)
    message(STATUS "Found GLEW: ${GLEW_LIBRARY}")
endif()

# GL headers might be in sysroot for cross-compiled conda envs
if(DEFINED ENV{CONDA_PREFIX})
    set(SYSROOT "$ENV{CONDA_PREFIX}/x86_64-conda-linux-gnu/sysroot")
    if(EXISTS "${SYSROOT}/usr/include/GL/gl.h")
        include_directories(SYSTEM "${SYSROOT}/usr/include")
        message(STATUS "Using sysroot GL headers from: ${SYSROOT}/usr/include")
    endif()
endif()

# ─── Proto Generation ───
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../proto")
set(PROTO_FILE "${PROTO_DIR}/blob_service.proto")
set(PROTO_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.cc")
set(PROTO_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.h")
set(GRPC_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.cc")
set(GRPC_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.h")

# Find protoc and grpc_cpp_plugin
find_program(PROTOC protoc)
find_program(GRPC_CPP_PLUGIN grpc_cpp_plugin)

add_custom_command(
    OUTPUT ${PROTO_SRC} ${PROTO_HDR} ${GRPC_SRC} ${GRPC_HDR}
    COMMAND ${PROTOC}
    ARGS --grpc_out=${CMAKE_CURRENT_BINARY_DIR}
         --cpp_out=${CMAKE_CURRENT_BINARY_DIR}
         --plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN}
         -I ${PROTO_DIR}
         ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    COMMENT "Generating gRPC/Protobuf C++ stubs"
)

# ─── Source Files ───
include_directories(${CMAKE_CURRENT_BINARY_DIR})
include_directories(src)

file(GLOB_RECURSE SRC_FILES
    "src/*.cpp"
    "src/*.h"
)

# ─── Executable ───
add_executable(blob_overlay ${SRC_FILES} ${PROTO_SRC} ${GRPC_SRC})

target_link_libraries(blob_overlay
    SDL2::SDL2
    OpenGL::GL
    gRPC::grpc++
    gRPC::grpc
    protobuf::libprotobuf
)

if(HAS_GLEW)
    target_include_directories(blob_overlay PRIVATE ${GLEW_INCLUDE_DIR})
    target_link_libraries(blob_overlay ${GLEW_LIBRARY})
    target_compile_definitions(blob_overlay PRIVATE HAS_GLEW=1)
endif()

# ─── Compiler Warnings ───
target_compile_options(blob_overlay PRIVATE
    -Wall -Wextra -Wpedantic
    -Wno-unused-parameter
    -Wno-unused-variable
)
