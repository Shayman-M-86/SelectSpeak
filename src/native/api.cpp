#include "api.h"

std::uint32_t ss_api_version()
{
    return SELECTSPEAK_NATIVE_API_VERSION;
}

void ss_shutdown()
{
    ss_input_stop();
    ss_voice_shutdown();
}
