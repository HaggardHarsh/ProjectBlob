#include "blob/physics.h"
#include <cstdlib>

BlobPhysics::BlobPhysics() {
    int numPoints = 16;
    float radius = 50.0f;
    
    // Center point
    points.push_back({{400, 300}, {400, 300}, {0, 0}, 2.0f});
    
    // Perimeter points
    for (int i = 0; i < numPoints; ++i) {
        float angle = i * 2.0f * M_PI / numPoints;
        Vec2 p = {400 + std::cos(angle) * radius, 300 + std::sin(angle) * radius};
        points.push_back({p, p, {0, 0}, 1.0f});
        
        // Connect to center
        springs.push_back({0, i + 1, radius, 10.0f, 1.0f});
        
        // Connect to previous perimeter point
        if (i > 0) {
            float dist = radius * 2.0f * std::sin(M_PI / numPoints);
            springs.push_back({i, i + 1, dist, 15.0f, 1.0f});
        }
    }
    
    // Close the loop
    float dist = radius * 2.0f * std::sin(M_PI / numPoints);
    springs.push_back({numPoints, 1, dist, 15.0f, 1.0f});
}

void BlobPhysics::update(float dt) {
    // Verlet integration
    for (auto& p : points) {
        Vec2 temp = p.pos;
        p.pos = p.pos + (p.pos - p.oldPos) * 0.99f + p.accel * (dt * dt);
        p.oldPos = temp;
        p.accel = {0, gravity}; // Reset accel to just gravity
    }
    
    // Spring forces
    for (const auto& s : springs) {
        Point& p1 = points[s.p1];
        Point& p2 = points[s.p2];
        
        Vec2 delta = p2.pos - p1.pos;
        float dist = std::sqrt(delta.x * delta.x + delta.y * delta.y);
        
        if (dist > 0.001f) {
            float diff = (dist - s.restLength) / dist;
            Vec2 force = delta * diff * s.k;
            p1.accel = p1.accel + force * (1.0f / p1.mass);
            p2.accel = p2.accel - force * (1.0f / p2.mass);
        }
    }
    
    // Floor collision
    float floorY = 550.0f;
    for (auto& p : points) {
        if (p.pos.y > floorY) {
            p.pos.y = floorY;
            // Add some friction
            p.pos.x = p.oldPos.x + (p.pos.x - p.oldPos.x) * 0.8f;
        }
    }
}

std::vector<Vec2> BlobPhysics::getVertices() const {
    std::vector<Vec2> v;
    for (size_t i = 1; i < points.size(); ++i) {
        v.push_back(points[i].pos);
    }
    return v;
}

void BlobPhysics::applyForce(Vec2 force) {
    for (auto& p : points) p.accel = p.accel + force;
}

void BlobPhysics::jiggle() {
    for (auto& p : points) {
        float jx = (std::rand() % 100 - 50) * 10.0f;
        float jy = (std::rand() % 100 - 50) * 10.0f;
        p.accel = p.accel + Vec2{jx, jy};
    }
}

void BlobPhysics::squash(float amount) {
    for (auto& p : points) {
        p.pos.y += (p.pos.y - points[0].pos.y) * amount;
        p.pos.x -= (p.pos.x - points[0].pos.x) * amount * 0.5f; // Maintain volume approx
    }
}
