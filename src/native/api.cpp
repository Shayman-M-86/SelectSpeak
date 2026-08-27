#include "api.h"

#include "audio/audio_engine.h"

std::uint32_t ss_api_version()
{
    return SELECTSPEAK_NATIVE_API_VERSION;
}

void ss_shutdown()
{
    // Before ss_input_stop, which only tears down the input message loop: an
    // OCR capture still registered would otherwise keep its hotkey and worker
    // alive past shutdown, where it can call a stale client callback or reach
    // native state the bridge considers closed. Unregistering the hotkey runs
    // through that same message loop, so it has to happen while it is up.
    ss_ocr_stop();
    ss_input_stop();
    ss_voice_shutdown();
    selectspeak::audio::ShutdownProductionAudioEngine();
}
