using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace SelectSpeak.UI;

/// <summary>
/// Newline-delimited JSON over a named pipe.
/// Python owns the application state; this side only renders what it is told
/// and reports back what the user pressed.
/// </summary>
public sealed class PlayerBridge : IDisposable
{
    private readonly string _pipeName;
    private readonly CancellationTokenSource _cancellation = new();
    private NamedPipeClientStream? _pipe;
    private StreamWriter? _writer;
    private readonly SemaphoreSlim _writeLock = new(1, 1);

    /// <summary>Raised on a background thread for every message from Python.</summary>
    public event Action<JsonElement>? MessageReceived;

    public event Action<bool>? ConnectionChanged;

    public PlayerBridge(string pipeName) => _pipeName = pipeName;

    public async Task RunAsync()
    {
        while (!_cancellation.IsCancellationRequested)
        {
            try
            {
                _pipe = new NamedPipeClientStream(".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
                await _pipe.ConnectAsync(2000, _cancellation.Token).ConfigureAwait(false);
                _writer = new StreamWriter(_pipe) { AutoFlush = true };
                ConnectionChanged?.Invoke(true);

                using var reader = new StreamReader(_pipe);
                while (!_cancellation.IsCancellationRequested)
                {
                    var line = await reader.ReadLineAsync().ConfigureAwait(false);
                    if (line is null)
                    {
                        break; // Python closed the pipe.
                    }
                    if (line.Length == 0)
                    {
                        continue;
                    }

                    try
                    {
                        using var document = JsonDocument.Parse(line);
                        MessageReceived?.Invoke(document.RootElement.Clone());
                    }
                    catch (JsonException)
                    {
                        // A malformed line must never take the UI down.
                    }
                }
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception)
            {
                // Fall through to the reconnect delay below.
            }

            ConnectionChanged?.Invoke(false);
            _writer = null;
            _pipe?.Dispose();
            _pipe = null;

            if (!_cancellation.IsCancellationRequested)
            {
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
    }

    /// <summary>Send a user intent back to Python. Never throws.</summary>
    public async Task SendAsync(string type, IDictionary<string, object?>? fields = null)
    {
        var writer = _writer;
        if (writer is null)
        {
            return;
        }

        var payload = new Dictionary<string, object?> { ["type"] = type };
        if (fields is not null)
        {
            foreach (var pair in fields)
            {
                payload[pair.Key] = pair.Value;
            }
        }

        await _writeLock.WaitAsync().ConfigureAwait(false);
        try
        {
            await writer.WriteLineAsync(JsonSerializer.Serialize(payload)).ConfigureAwait(false);
        }
        catch (Exception)
        {
            // A dropped pipe is handled by the read loop's reconnect.
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public void Dispose()
    {
        _cancellation.Cancel();
        _pipe?.Dispose();
        _cancellation.Dispose();
        _writeLock.Dispose();
    }
}
