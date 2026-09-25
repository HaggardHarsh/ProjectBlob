#include "state_machine.h"

BlobStateMachine::BlobStateMachine() {}

void BlobStateMachine::update(float dt) {
    stateTime += dt;
}

void BlobStateMachine::changeState(BlobState newState) {
    currentState = newState;
    stateTime = 0.0f;
}
