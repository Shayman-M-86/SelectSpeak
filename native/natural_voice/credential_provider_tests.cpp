#include "credential_provider.h"

#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

namespace {
bool expect_equal(const std::optional<std::string>& actual,
                  const std::string& expected, const char* test)
{
    if (actual && *actual == expected) {
        return true;
    }
    std::cerr << test << " failed\n";
    return false;
}
}  // namespace

int main()
{
    bool passed = true;
    const std::string utf8_credential = "License:alpha-2774316-omega";
    std::vector<std::uint8_t> utf8 = {9, 0};
    utf8.insert(utf8.end(), utf8_credential.begin(), utf8_credential.end());
    utf8.insert(utf8.end(), {0, 7});
    passed &= expect_equal(extract_installed_narrator_credential(utf8),
                           utf8_credential, "UTF-8 credential");

    const std::string utf16_credential = "Wide-2774316-license";
    std::vector<std::uint8_t> utf16 = {8, 0, 0, 0};
    for (const auto character : utf16_credential) {
        utf16.push_back(static_cast<std::uint8_t>(character));
        utf16.push_back(0);
    }
    utf16.insert(utf16.end(), {0, 0, 3});
    passed &= expect_equal(extract_installed_narrator_credential(utf16),
                           utf16_credential, "UTF-16 credential");

    passed &= !extract_installed_narrator_credential({1, 2, 3}).has_value();
    if (!passed) {
        return 1;
    }
    std::cout << "credential provider tests passed\n";
    return 0;
}
