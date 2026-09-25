.PHONY: all proto frontend backend-install run clean

PROTO_DIR := proto
FRONTEND_DIR := frontend_cpp
BACKEND_DIR := backend_python
PROTO_FILE := $(PROTO_DIR)/blob_service.proto

# ─── Default target ───
all: proto frontend backend-install

# ─── Generate Protobuf/gRPC stubs for both C++ and Python ───
proto:
	@echo "═══ Generating Protobuf stubs ═══"
	# Python stubs
	python -m grpc_tools.protoc \
		-I$(PROTO_DIR) \
		--python_out=$(BACKEND_DIR)/blob/ipc \
		--pyi_out=$(BACKEND_DIR)/blob/ipc \
		--grpc_python_out=$(BACKEND_DIR)/blob/ipc \
		$(PROTO_FILE)
	@echo "✓ Python protobuf stubs generated"
	# C++ stubs (generated during cmake build)
	@echo "✓ C++ stubs will be generated during frontend build"

# ─── Build C++ frontend ───
frontend:
	@echo "═══ Building C++ Frontend ═══"
	mkdir -p $(FRONTEND_DIR)/build
	cd $(FRONTEND_DIR)/build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j$$(nproc)
	@echo "✓ Frontend built: $(FRONTEND_DIR)/build/blob_overlay"

frontend-debug:
	@echo "═══ Building C++ Frontend (Debug) ═══"
	mkdir -p $(FRONTEND_DIR)/build-debug
	cd $(FRONTEND_DIR)/build-debug && cmake .. -DCMAKE_BUILD_TYPE=Debug && make -j$$(nproc)
	@echo "✓ Frontend debug built: $(FRONTEND_DIR)/build-debug/blob_overlay"

# ─── Install Python backend ───
backend-install:
	@echo "═══ Installing Python Backend ═══"
	cd $(BACKEND_DIR) && pip install -e ".[dev]"
	@echo "✓ Backend installed"

# ─── Run both components ───
run: run-backend run-frontend

run-backend:
	@echo "═══ Starting Python Backend ═══"
	cd $(BACKEND_DIR) && blob-backend &
	@sleep 2  # Give backend time to start gRPC server

run-frontend:
	@echo "═══ Starting C++ Frontend ═══"
	$(FRONTEND_DIR)/build/blob_overlay

run-backend-only:
	@echo "═══ Starting Python Backend (foreground) ═══"
	cd $(BACKEND_DIR) && blob-backend

# ─── Tests ───
test: test-backend test-frontend

test-backend:
	@echo "═══ Running Python Tests ═══"
	cd $(BACKEND_DIR) && python -m pytest tests/ -v

test-frontend:
	@echo "═══ Running C++ Tests ═══"
	cd $(FRONTEND_DIR)/build && ctest --output-on-failure

# ─── Clean ───
clean:
	rm -rf $(FRONTEND_DIR)/build $(FRONTEND_DIR)/build-debug
	rm -f $(BACKEND_DIR)/blob/ipc/blob_service_pb2*.py
	rm -f $(BACKEND_DIR)/blob/ipc/blob_service_pb2*.pyi
	@echo "✓ Cleaned build artifacts"

# ─── Help ───
help:
	@echo "Project Blob - Build Targets"
	@echo "═══════════════════════════════"
	@echo "  make all             Build everything (proto + frontend + backend)"
	@echo "  make proto           Generate protobuf stubs"
	@echo "  make frontend        Build C++ frontend (Release)"
	@echo "  make frontend-debug  Build C++ frontend (Debug)"
	@echo "  make backend-install Install Python backend"
	@echo "  make run             Run both backend and frontend"
	@echo "  make test            Run all tests"
	@echo "  make clean           Clean build artifacts"
