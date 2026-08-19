using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace SelectSpeak.UI.Bridge;

/// <summary>
/// Newline-delimited JSON over a named pipe.
///
/// Python is the server so it can start, stop and restart independently; this
/// side reconnects on its own, which means the UI can be launched first or
/// survive a backend restart without special handling.
///
/// Deliberately minimal: connect, read lines into <see cref="PlayerMessage"/>,
/// write intent lines. No request/response, no correlation ids, no RPC.
/// </summary>
public sealed class NamedPipePlayerBridge : IPlayerBridge
{
    public const string DefaultPipeName = "selectspeak-ui";

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly string _pipeName;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly SemaphoreSlim _writeLock = new(1, 1);

    private StreamWriter? _writer;

    public NamedPipePlayerBridge(string pipeName = DefaultPipeName) => _pipeName = pipeName;

    /// <inheritdoc />
    public event Action<PlayerMessage>? MessageReceived;

    /// <inheritdoc />
    public event Action<bool>? ConnectionChanged;

    /// <inheritdoc />
    public async Task RunAsync()
    {
        while (!_cancellation.IsCancellationRequested)
        {
            try
            {
                await ReadUntilDisconnectedAsync().ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception)
            {
                // Any pipe failure is treated the same way: drop back to the
                // reconnect delay below. A backend that is not running yet is
                // the normal case, not an error.
            }

            _writer = null;
            ConnectionChanged?.Invoke(false);

            try
            {
                await Task.Delay(500, _cancellation.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
    }

    private async Task ReadUntilDisconnectedAsync()
    {
        using var pipe = new NamedPipeClientStream(
            ".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);

        await pipe.ConnectAsync(2000, _cancellation.Token).ConfigureAwait(false);

        _writer = new StreamWriter(pipe) { AutoFlush = true };
        ConnectionChanged?.Invoke(true);

        using var reader = new StreamReader(pipe);
        while (!_cancellation.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync().ConfigureAwait(false);
            if (line is null)
            {
                return; // Backend closed the pipe.
            }
            if (line.Length == 0)
            {
                continue;
            }

            if (TryParse(line, out var message))
            {
                MessageReceived?.Invoke(message);
            }
        }
    }

    private static bool TryParse(string line, out PlayerMessage message)
    {
        try
        {
            message = JsonSerializer.Deserialize<PlayerMessage>(line, SerializerOptions);
            return !string.IsNullOrEmpty(message.Type);
        }
        catch (JsonException)
        {
            // A malformed line must never take the UI down.
            message = default;
            return false;
        }
    }

    /// <inheritdoc />
    public Task SendAsync(string intent) => WriteAsync(intent, fields: null);

    /// <inheritdoc />
    public Task SendAsync(string intent, IReadOnlyDictionary<string, string> fields) =>
        WriteAsync(intent, fields);

    private async Task WriteAsync(string intent, IReadOnlyDictionary<string, string>? fields)
    {
        var writer = _writer;
        if (writer is null)
        {
            return; // Not connected; intents are dropped rather than queued.
        }

        var message = new Dictionary<string, string> { ["type"] = intent };
        if (fields is not null)
        {
            foreach (var pair in fields)
            {
                message[pair.Key] = pair.Value;
            }
        }

        var payload = JsonSerializer.Serialize(message);

        await _writeLock.WaitAsync().ConfigureAwait(false);
        try
        {
            await writer.WriteLineAsync(payload).ConfigureAwait(false);
        }
        catch (Exception)
        {
            // A dropped pipe is picked up by the read loop's reconnect.
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public void Dispose()
    {
        _cancellation.Cancel();
        _cancellation.Dispose();
        _writeLock.Dispose();
    }
}
