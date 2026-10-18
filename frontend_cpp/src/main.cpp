#include "app/application.h"
#include <exception>
#include <iostream>

int main(int argc, char** argv) {
    try { return runDesktop(argc, argv); }
    catch (const std::exception& error) { std::cerr << "Blob: " << error.what() << '\n'; return 1; }
}
