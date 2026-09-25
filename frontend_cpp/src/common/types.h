#pragma once
#include <cmath>

/**
 * Common types shared across the Project Blob frontend.
 */

struct Vec2 {
    float x = 0.0f;
    float y = 0.0f;

    Vec2() = default;
    Vec2(float x_, float y_) : x(x_), y(y_) {}

    Vec2 operator+(const Vec2& o) const { return {x + o.x, y + o.y}; }
    Vec2 operator-(const Vec2& o) const { return {x - o.x, y - o.y}; }
    Vec2 operator*(float s) const { return {x * s, y * s}; }
    Vec2& operator+=(const Vec2& o) { x += o.x; y += o.y; return *this; }
    Vec2& operator-=(const Vec2& o) { x -= o.x; y -= o.y; return *this; }

    float length() const { return std::sqrt(x * x + y * y); }
    Vec2 normalized() const {
        float len = length();
        return (len > 0.0001f) ? Vec2{x / len, y / len} : Vec2{0, 0};
    }
};

struct Color {
    unsigned char r = 255;
    unsigned char g = 255;
    unsigned char b = 255;
    unsigned char a = 255;
};
