#include "grpc_client.h"

#include <chrono>
#include <utility>
#include <fstream>
#include <cstdlib>

static void authorize(grpc::ClientContext& context) {
    const char* configured = std::getenv("BLOB_IPC_TOKEN_PATH");
    const char* home = std::getenv("HOME");
    const std::string path = configured ? configured : (home ? std::string(home) + "/.blob/ipc.token" : "");
    std::ifstream file(path);
    std::string token;
    if (file >> token) context.AddMetadata("x-blob-token", token);
}

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
    if (!running_ || !connected_ || outbound_.size() >= 100) return false;
    if (event.has_user_message() && event.user_message().text() == "/stop") outbound_.push_front(std::move(event));
    else outbound_.push_back(std::move(event));
    condition_.notify_one();
    return true;
}

bool GrpcClient::sendMessage(const std::string& text) {
    if (text.empty()) return false;
    blob::FrontendEvent event;
    event.mutable_user_message()->set_text(text);
    return enqueue(std::move(event));
}

bool GrpcClient::attachFiles(const std::vector<std::string>& paths) {
    if (paths.empty()) return false;
    blob::FrontendEvent event;
    for (const auto& path : paths) event.mutable_attachment_drop()->add_file_paths(path);
    return enqueue(std::move(event));
}

bool GrpcClient::installSkill(const std::string& path) {
    if (path.empty()) return false;
    blob::FrontendEvent event;
    event.mutable_skill_pill_drop()->set_file_path(path);
    return enqueue(std::move(event));
}

bool GrpcClient::togglePrivacy() {
    if (!connected_) return false;
    privacyToggle_ = true;
    condition_.notify_all();
    return true;
}

bool GrpcClient::setCloudEnabled(bool enabled) {
    if (!connected_) return false;
    cloudChange_ = enabled ? 1 : 0;
    condition_.notify_all();
    return true;
}

bool GrpcClient::proactiveFeedback(const std::string& id, blob::ProactiveFeedback::Action action) {
    blob::FrontendEvent event;
    event.mutable_proactive_feedback()->set_approach_id(id);
    event.mutable_proactive_feedback()->set_action(action);
    return enqueue(std::move(event));
}

bool GrpcClient::proactiveControl(bool quietToday) {
    if (!running_) return false;
    proactiveChange_ = quietToday ? 1 : 0;
    condition_.notify_all();
    return true;
}

void GrpcClient::run() {
    while (running_) {
        if (!channel_->WaitForConnected(std::chrono::system_clock::now() + 1s)) continue;
        if (!running_) break;

        grpc::ClientContext context;
        authorize(context);
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
                condition_.wait_for(lock, 5s, [&]() { return !running_ || !streamOpen || !outbound_.empty() || privacyToggle_ || cloudChange_ != -1 || proactiveChange_ != -1; });
                if (!running_ || !streamOpen) break;
                if (!outbound_.empty()) {
                    event = std::move(outbound_.front());
                    outbound_.pop_front();
                    hasEvent = true;
                }
            }
            const bool toggle = privacyToggle_.exchange(false);
            const int cloud = cloudChange_.exchange(-1);
            proactiveApplying_ = proactiveChange_.load() != -1;
            const int proactive = proactiveChange_.exchange(-1);
            if (toggle || cloud != -1 || proactive != -1) {
                grpc::ClientContext controlContext;
                authorize(controlContext);
                controlContext.set_deadline(std::chrono::system_clock::now() + 2s);
                blob::ConfigUpdate request;
                if (toggle) (*request.mutable_settings())["privacy_paused"] = "toggle";
                else if (cloud != -1) (*request.mutable_settings())["cloud_enabled"] = cloud ? "true" : "false";
                else (*request.mutable_settings())["proactive_mode"] = proactive ? "quiet" : "off";
                // Preserve a simultaneous explicit cloud action for the next pass.
                if (toggle && cloud != -1) cloudChange_ = cloud;
                if ((toggle || cloud != -1) && proactive != -1) proactiveChange_ = proactive;
                blob::ConfigUpdateResponse response;
                const auto result = stub_->UpdateConfig(&controlContext, request, &response);
                if (!result.ok() || !response.success()) {
                    if (!toggle && cloud == -1 && proactive != -1) {
                        int empty = -1;
                        proactiveChange_.compare_exchange_strong(empty, proactive);
                        std::this_thread::sleep_for(1s);
                    } else {
                        blob::BackendEvent failure;
                        failure.mutable_notification()->set_text("That setting was not confirmed. Reconnect or check /privacy status before trying again.");
                        inbound_.push(std::move(failure));
                    }
                }
            }
            proactiveApplying_ = false;
            if (!hasEvent) {
                auto* heartbeat = event.mutable_heartbeat();
                heartbeat->set_frontend_uptime_ms(0);
                heartbeat->set_client_kind(blob::HeartbeatPing::OVERLAY);
                heartbeat->set_proactive_bubbles(true);
                heartbeat->set_overlay_visible(visible_);
                heartbeat->set_desktop_width(desktopWidth_);
                heartbeat->set_desktop_height(desktopHeight_);
            }
            if (!stream->Write(event)) {
                // A failed write may already have reached the backend. Never replay it.
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
        {
            std::lock_guard<std::mutex> lock(mutex_);
            outbound_.clear();
        }
        privacyToggle_ = false;
        cloudChange_ = -1;
        if (running_) std::this_thread::sleep_for(500ms);
    }
}
