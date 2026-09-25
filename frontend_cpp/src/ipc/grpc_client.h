#pragma once
#include <string>

class GrpcClient {
public:
    GrpcClient(const std::string& address);
    ~GrpcClient();
    void start();
    void stop();

private:
    std::string address;
};
