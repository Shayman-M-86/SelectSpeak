#pragma once

#include <string>

// This compatibility value is intentionally isolated: Microsoft does not expose
// Narrator voices as a supported third-party API and has changed its protection.
std::string legacy_narrator_credential();
