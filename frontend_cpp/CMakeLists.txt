cmake_minimum_required(VERSION 3.15)
project(blob_frontend CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ─── Find Dependencies ───
find_package(SDL2 REQUIRED CONFIG)
find_package(gRPC CONFIG REQUIRED)

# ─── Proto Generation ───
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../proto")
set(PROTO_FILE "${PROTO_DIR}/blob_service.proto")
set(PROTO_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.cc")
set(PROTO_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.pb.h")
set(GRPC_SRC "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.cc")
set(GRPC_HDR "${CMAKE_CURRENT_BINARY_DIR}/blob_service.grpc.pb.h")

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
    gRPC::grpc++
    gRPC::grpc
    protobuf::libprotobuf
)

# ─── Compiler Warnings ───
target_compile_options(blob_overlay PRIVATE
    -Wall -Wextra -Wpedantic
    -Wno-unused-parameter
    -Wno-unused-variable
)
