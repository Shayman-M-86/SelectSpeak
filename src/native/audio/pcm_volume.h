#pragma once

#include <cstdint>
#include <cstring>
#include <vector>

namespace selectspeak::audio {

inline void ScalePcm16(std::vector<std::uint8_t>& pcm,
                       const std::uint32_t volume_percent) noexcept
{
    const auto signed_volume = static_cast<std::int32_t>(volume_percent);
    for (std::size_t offset = 0; offset + sizeof(std::int16_t) <= pcm.size();
         offset += sizeof(std::int16_t)) {
        std::int16_t sample = 0;
        std::memcpy(&sample, pcm.data() + offset, sizeof(sample));
        const auto scaled = static_cast<std::int32_t>(sample) * signed_volume /
                            100;
        sample = static_cast<std::int16_t>(scaled);
        std::memcpy(pcm.data() + offset, &sample, sizeof(sample));
    }
}

}  // namespace selectspeak::audio
