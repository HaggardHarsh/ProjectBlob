cmake_minimum_required(VERSION 3.15)
project(blob_frontend CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ─── Find Dependencies ───
find_package(SDL2 REQUIRED CONFIG)
find_package(gRPC CONFIG REQUIRED)
find_package(X11 QUIET)

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

add_library(blob_protocol STATIC ${PROTO_SRC} ${GRPC_SRC})
target_link_libraries(blob_protocol PUBLIC gRPC::grpc++ gRPC::grpc protobuf::libprotobuf)

file(GLOB_RECURSE SRC_FILES
    "src/*.cpp"
    "src/*.h"
)

# ─── Executable ───
add_executable(blob_overlay ${SRC_FILES})
file(COPY "${CMAKE_CURRENT_SOURCE_DIR}/data/OpenSans-Regular.ttf"
          "${CMAKE_CURRENT_SOURCE_DIR}/data/OpenSans-LICENSE.txt"
     DESTINATION "${CMAKE_CURRENT_BINARY_DIR}/data")

target_link_libraries(blob_overlay
    SDL2::SDL2
    gRPC::grpc++
    gRPC::grpc
    protobuf::libprotobuf
    blob_protocol
)

if(X11_FOUND)
    target_compile_definitions(blob_overlay PRIVATE BLOB_HAVE_X11=1)
    target_include_directories(blob_overlay PRIVATE ${X11_INCLUDE_DIR})
    target_link_libraries(blob_overlay ${X11_LIBRARIES})
endif()

# ─── Compiler Warnings ───
target_compile_options(blob_overlay PRIVATE
    -Wall -Wextra -Wpedantic
    -Wno-unused-parameter
    -Wno-unused-variable
)

add_executable(blob_ipc_smoke
    tests/grpc_client_smoke.cpp
    src/ipc/grpc_client.cpp
)
target_include_directories(blob_ipc_smoke PRIVATE ${CMAKE_CURRENT_BINARY_DIR} src)
target_link_libraries(blob_ipc_smoke blob_protocol)

enable_testing()
add_executable(blob_render_smoke
    tests/render_smoke.cpp
    src/blob/animation.cpp
    src/blob/physics.cpp
    src/overlay/renderer.cpp
)
target_include_directories(blob_render_smoke PRIVATE src)
target_link_libraries(blob_render_smoke SDL2::SDL2)
add_test(NAME blob_render_smoke COMMAND blob_render_smoke)
set_tests_properties(blob_render_smoke PROPERTIES ENVIRONMENT "SDL_VIDEODRIVER=dummy")

add_executable(blob_chat_smoke
    tests/chat_smoke.cpp src/ui/chat.cpp src/ui/text.cpp src/ipc/grpc_client.cpp)
target_include_directories(blob_chat_smoke PRIVATE ${CMAKE_CURRENT_BINARY_DIR} src)
target_link_libraries(blob_chat_smoke SDL2::SDL2 blob_protocol)
add_test(NAME blob_chat_smoke COMMAND blob_chat_smoke)
set_tests_properties(blob_chat_smoke PROPERTIES ENVIRONMENT "SDL_VIDEODRIVER=dummy")
