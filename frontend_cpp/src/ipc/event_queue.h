#pragma once
#include <mutex>
#include <queue>
#include <optional>
#include <vector>

template <typename T>
class EventQueue {
public:
    void push(T event) {
        std::lock_guard<std::mutex> lock(mtx);
        q.push(event);
    }
    
    std::optional<T> tryPop() {
        std::lock_guard<std::mutex> lock(mtx);
        if (q.empty()) return std::nullopt;
        T val = q.front();
        q.pop();
        return val;
    }
    
    std::vector<T> popAll() {
        std::lock_guard<std::mutex> lock(mtx);
        std::vector<T> res;
        while (!q.empty()) {
            res.push_back(q.front());
            q.pop();
        }
        return res;
    }

private:
    std::queue<T> q;
    std::mutex mtx;
};
