#pragma once

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <deque>
#include <string>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include "blob_service.grpc.pb.h"
#include "ipc/event_queue.h"

class GrpcClient {
public:
    explicit GrpcClient(const std::string& address);
    ~GrpcClient();
    void start();
    void stop();
    bool sendMessage(const std::string& text);
    bool attachFiles(const std::vector<std::string>& paths);
    bool installSkill(const std::string& path);
    void togglePrivacy();
    std::optional<blob::BackendEvent> pollEvent() { return inbound_.tryPop(); }
    bool isConnected() const { return connected_.load(); }

private:
    bool enqueue(blob::FrontendEvent event);
    void run();

    std::string address_;
    std::shared_ptr<grpc::Channel> channel_;
    std::unique_ptr<blob::BlobService::Stub> stub_;
    std::thread worker_;
    std::atomic<bool> running_{false};
    std::atomic<bool> connected_{false};
    std::atomic<bool> privacyToggle_{false};
    std::mutex mutex_;
    std::condition_variable condition_;
    std::deque<blob::FrontendEvent> outbound_;
    EventQueue<blob::BackendEvent> inbound_;
    grpc::ClientContext* activeContext_ = nullptr; // Protected by mutex_.
};
