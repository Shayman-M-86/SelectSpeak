#pragma once

#include <algorithm>
#include <cstring>
#include <exception>
#include <string>
#include <utility>

namespace selectspeak::abi {

template <typename Size>
Size CopyString(const std::string& value, char* buffer, Size capacity)
{
    const auto required = static_cast<Size>(value.size() + 1);
    if (buffer != nullptr && capacity > 0) {
        const auto count = std::min<Size>(capacity - 1, required - 1);
        std::memcpy(buffer, value.data(), count);
        buffer[count] = '\0';
    }
    return required;
}

template <typename SetError>
void Report(SetError&& set_error, const char* message) noexcept
{
    try {
        set_error(message == nullptr ? "Unknown native error" : message);
    } catch (...) {
    }
}

template <typename SetError, typename Function>
int GuardInt(SetError&& set_error, Function&& function) noexcept
{
    try {
        return function();
    } catch (const std::exception& error) {
        Report(std::forward<SetError>(set_error), error.what());
    } catch (...) {
        Report(std::forward<SetError>(set_error), "Unknown native exception");
    }
    return 1;
}

template <typename SetError, typename Function>
void GuardVoid(SetError&& set_error, Function&& function) noexcept
{
    try {
        function();
    } catch (const std::exception& error) {
        Report(std::forward<SetError>(set_error), error.what());
    } catch (...) {
        Report(std::forward<SetError>(set_error), "Unknown native exception");
    }
}

template <typename Result, typename SetError, typename Function>
Result GuardResult(Result failure, SetError&& set_error,
                   Function&& function) noexcept
{
    try {
        return function();
    } catch (const std::exception& error) {
        Report(std::forward<SetError>(set_error), error.what());
    } catch (...) {
        Report(std::forward<SetError>(set_error), "Unknown native exception");
    }
    return failure;
}

}  // namespace selectspeak::abi
