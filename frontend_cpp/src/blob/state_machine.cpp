#include "state_machine.h"

BlobStateMachine::BlobStateMachine() {}

void BlobStateMachine::update(float dt) {
    stateTime += dt;
}

void BlobStateMachine::changeState(BlobState newState) {
    if (newState == currentState) return;
    currentState = newState;
    stateTime = 0.0f;
}
