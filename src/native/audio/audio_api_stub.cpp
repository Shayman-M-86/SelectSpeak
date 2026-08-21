#include "../api.h"

#include <cstddef>

std::uint32_t ss_audio_request_create(
    const std::uint64_t request_id, const ss_audio_format_t* const format,
    const std::uint32_t,
    const ss_audio_event_callback_t callback, void* const,
    ss_audio_request_handle_t* const handle)
{
    if (handle == nullptr) {
        return SS_STATUS_INVALID_ARGUMENT;
    }
    *handle = SS_INVALID_AUDIO_REQUEST_HANDLE;
    if (request_id == 0) {
        return SS_STATUS_INVALID_REQUEST;
    }
    if (format == nullptr || format->size != sizeof(ss_audio_format_t) ||
        format->sample_rate_hz == 0 || format->channel_count == 0 ||
        format->sample_format != SS_SAMPLE_FORMAT_PCM_S16_LE ||
        callback == nullptr) {
        return SS_STATUS_INVALID_ARGUMENT;
    }

    // Package J replaces this non-accepting ABI stub with the request-scoped
    // XAudio2 implementation. No lifecycle callback is emitted because the
    // request was not accepted and no handle was created.
    return SS_STATUS_DEVICE_ERROR;
}

std::uint32_t ss_audio_request_submit(
    const ss_audio_request_handle_t, const void*, const std::uint64_t,
    const ss_audio_boundary_t*, const std::uint32_t,
    ss_audio_submit_result_t* const result)
{
    if (result != nullptr) {
        result->accepted_frames = 0;
        result->buffered_frames_after_submit = 0;
    }
    return SS_STATUS_INVALID_HANDLE;
}

std::uint32_t ss_audio_request_finish_input(const ss_audio_request_handle_t)
{
    return SS_STATUS_INVALID_HANDLE;
}

std::uint32_t ss_audio_request_pause(const ss_audio_request_handle_t)
{
    return SS_STATUS_INVALID_HANDLE;
}

std::uint32_t ss_audio_request_resume(const ss_audio_request_handle_t)
{
    return SS_STATUS_INVALID_HANDLE;
}

std::uint32_t ss_audio_request_stop(const ss_audio_request_handle_t,
                                    const std::uint32_t)
{
    return SS_STATUS_INVALID_HANDLE;
}

std::uint32_t ss_audio_request_destroy(const ss_audio_request_handle_t)
{
    return SS_STATUS_INVALID_HANDLE;
}
