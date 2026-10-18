.PHONY: all proto frontend backend-install run clean

PROTO_DIR := proto
FRONTEND_DIR := frontend_cpp
BACKEND_DIR := backend_python
PROTO_FILE := $(PROTO_DIR)/blob_service.proto

MANAGED_ROOT := $(abspath .runtime/desktop/current)
VENV_BIN := $(if $(wildcard $(MANAGED_ROOT)/venv/bin),$(MANAGED_ROOT)/venv/bin,$(if $(wildcard venv/bin),$(abspath venv/bin),))
FRONTEND_BINARY := $(if $(wildcard $(MANAGED_ROOT)/frontend/blob_overlay),$(MANAGED_ROOT)/frontend/blob_overlay,$(FRONTEND_DIR)/build/blob_overlay)
PYTHON := $(if $(VENV_BIN),$(VENV_BIN)/python,python)
PIP := $(if $(VENV_BIN),$(VENV_BIN)/pip,pip)
BLOB_BACKEND := $(if $(VENV_BIN),$(VENV_BIN)/blob-backend,blob-backend)

# ─── Default target ───
all: proto frontend backend-install

# ─── Generate Protobuf/gRPC stubs for both C++ and Python ───
proto:
	@echo "═══ Generating Protobuf stubs ═══"
	# Python stubs
	$(PYTHON) -m grpc_tools.protoc \
		-I$(PROTO_DIR) \
		--python_out=$(BACKEND_DIR)/blob/ipc \
		--pyi_out=$(BACKEND_DIR)/blob/ipc \
		--grpc_python_out=$(BACKEND_DIR)/blob/ipc \
		$(PROTO_FILE)
	$(PYTHON) -c 'from pathlib import Path; p = Path("$(BACKEND_DIR)/blob/ipc/blob_service_pb2_grpc.py"); p.write_text(p.read_text().replace("import blob_service_pb2 as blob__service__pb2", "from . import blob_service_pb2 as blob__service__pb2"))'
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
	cd $(BACKEND_DIR) && $(PIP) install -e ".[dev]"
	@echo "✓ Backend installed"

# ─── Run both components ───
run:
	@echo "═══ Starting C++ Frontend (Desktop Overlay) ═══"
	@$(FRONTEND_BINARY) & FRONTEND_PID=$$!; \
	trap 'kill $$FRONTEND_PID 2>/dev/null' EXIT INT TERM; \
	sleep 1; \
	echo "═══ Starting Python Backend (Interactive CLI) ═══"; \
	cd $(BACKEND_DIR) && $(BLOB_BACKEND)

run-backend: run-backend-only

run-frontend:
	@echo "═══ Starting C++ Frontend ═══"
	$(FRONTEND_BINARY)

run-backend-only:
	@echo "═══ Starting Python Backend (foreground) ═══"
	cd $(BACKEND_DIR) && $(BLOB_BACKEND)

# ─── Tests ───
test: test-backend test-frontend

test-backend:
	@echo "═══ Running Python Tests ═══"
	$(PYTHON) -m pytest $(BACKEND_DIR)/tests -q

test-frontend:
	@echo "═══ Running C++ Tests ═══"
	cd $(FRONTEND_DIR)/build && ctest --output-on-failure

run-daemon:
	$(PYTHON) -m blob.main --daemon

chat:
	$(PYTHON) -m blob.client

desktop-install:
	$(PYTHON) tools/install_desktop.py

awareness-install:
	$(PYTHON) tools/install_awareness.py

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
