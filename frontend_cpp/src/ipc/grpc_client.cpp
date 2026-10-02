#include "grpc_client.h"

#include <chrono>
#include <utility>

using namespace std::chrono_literals;

GrpcClient::GrpcClient(const std::string& address) : address_(address) {}
GrpcClient::~GrpcClient() { stop(); }

void GrpcClient::start() {
    if (running_.exchange(true)) return;
    channel_ = grpc::CreateChannel(address_, grpc::InsecureChannelCredentials());
    stub_ = blob::BlobService::NewStub(channel_);
    worker_ = std::thread(&GrpcClient::run, this);
}

void GrpcClient::stop() {
    if (!running_.exchange(false)) return;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (activeContext_) activeContext_->TryCancel();
    }
    condition_.notify_all();
    if (worker_.joinable()) worker_.join();
    connected_ = false;
}

bool GrpcClient::enqueue(blob::FrontendEvent event) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_ || outbound_.size() >= 100) return false;
    outbound_.push_back(std::move(event));
    condition_.notify_one();
    return true;
}

bool GrpcClient::sendMessage(const std::string& text, const std::vector<std::string>& attachments,
                             const std::string& request_id) {
    if (text.empty() && attachments.empty()) return false;
    blob::FrontendEvent event;
    event.mutable_user_message()->set_text(text);
    for (const auto& path : attachments) event.mutable_user_message()->add_attachments(path);
    event.mutable_user_message()->set_request_id(request_id);
    return enqueue(std::move(event));
}

bool GrpcClient::installSkill(const std::string& path) {
    if (path.empty()) return false;
    blob::FrontendEvent event;
    event.mutable_skill_pill_drop()->set_file_path(path);
    return enqueue(std::move(event));
}

void GrpcClient::run() {
    while (running_) {
        if (!channel_->WaitForConnected(std::chrono::system_clock::now() + 1s)) continue;
        if (!running_) break;

        grpc::ClientContext context;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            activeContext_ = &context;
        }
        auto stream = stub_->EventStream(&context);
        if (!stream) {
            std::lock_guard<std::mutex> lock(mutex_);
            activeContext_ = nullptr;
            continue;
        }
        connected_ = true;
        std::atomic<bool> streamOpen{true};
        std::thread reader([&]() {
            blob::BackendEvent event;
            while (running_ && stream->Read(&event)) {
                inbound_.push(event);
                event.Clear();
            }
            streamOpen = false;
            condition_.notify_all();
        });

        while (running_ && streamOpen) {
            blob::FrontendEvent event;
            bool hasEvent = false;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                condition_.wait_for(lock, 5s, [&]() { return !running_ || !streamOpen || !outbound_.empty(); });
                if (!running_ || !streamOpen) break;
                if (!outbound_.empty()) {
                    event = std::move(outbound_.front());
                    outbound_.pop_front();
                    hasEvent = true;
                }
            }
            if (!hasEvent) event.mutable_heartbeat()->set_frontend_uptime_ms(0);
            if (!stream->Write(event)) {
                if (hasEvent) {
                    std::lock_guard<std::mutex> lock(mutex_);
                    outbound_.push_front(std::move(event));
                }
                streamOpen = false;
                break;
            }
        }
        context.TryCancel();
        reader.join();
        stream->Finish();
        {
            std::lock_guard<std::mutex> lock(mutex_);
            activeContext_ = nullptr;
        }
        connected_ = false;
        if (running_) std::this_thread::sleep_for(500ms);
    }
}
