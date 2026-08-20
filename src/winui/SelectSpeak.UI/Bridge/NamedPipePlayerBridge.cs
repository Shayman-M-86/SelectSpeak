using System;
using System.Buffers;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
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
/// </summary>
public sealed class NamedPipePlayerBridge : IPlayerBridge
{
    public const string DefaultPipeName = "selectspeak-ui";

    // Selected text can be large, but a broken or hostile local pipe must not
    // be able to grow one line without limit. Four million UTF-16 characters
    // leaves ample room for normal reads while placing a hard ceiling on it.
    private const int MaxMessageCharacters = 4 * 1024 * 1024;
    private const int ReadBufferCharacters = 4096;

    private static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly string _pipeName;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private readonly object _runLock = new();

    private StreamWriter? _writer;
    private Task? _runTask;
    private int _connected;
    private int _disposed;

    public NamedPipePlayerBridge(string pipeName = DefaultPipeName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        _pipeName = pipeName;
    }

    /// <inheritdoc />
    public event Action<PlayerMessage>? MessageReceived;

    /// <inheritdoc />
    public event Action<bool>? ConnectionChanged;

    /// <inheritdoc />
    public Task RunAsync()
    {
        lock (_runLock)
        {
            ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
            return _runTask ??= RunCoreAsync();
        }
    }

    private async Task RunCoreAsync()
    {
        var cancellationToken = _cancellation.Token;

        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                await ReadUntilDisconnectedAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (IOException)
            {
                // A missing, restarted or malformed server all take the same
                // reconnect path. None is fatal to the UI process.
            }
            catch (TimeoutException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }

            PublishConnection(false);

            try
            {
                await Task.Delay(500, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }

        PublishConnection(false);
    }

    private async Task ReadUntilDisconnectedAsync(CancellationToken cancellationToken)
    {
        using var pipe = new NamedPipeClientStream(
            ".", _pipeName, PipeDirection.InOut, PipeOptions.Asynchronous);

        await pipe.ConnectAsync(2000, cancellationToken).ConfigureAwait(false);

        var writer = new StreamWriter(pipe, leaveOpen: true) { AutoFlush = true };
        using var reader = new StreamReader(pipe, leaveOpen: true);
        using var lines = new BoundedLineReader(reader, MaxMessageCharacters);

        Volatile.Write(ref _writer, writer);
        PublishConnection(true);

        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                var line = await lines.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is null)
                {
                    return; // Backend closed the pipe.
                }

                if (line.Length > 0 && TryParse(line, out var message))
                {
                    PublishMessage(message);
                }
            }
        }
        finally
        {
            Interlocked.CompareExchange(ref _writer, null, writer);

            // StreamWriter is not thread-safe. Wait for an in-flight send (and
            // let queued sends observe the null writer) before disposing it.
            await _writeLock.WaitAsync(CancellationToken.None).ConfigureAwait(false);
            try
            {
                writer.Dispose();
            }
            catch (IOException)
            {
                // The peer has already disconnected; there is nothing to flush.
            }
            finally
            {
                _writeLock.Release();
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
        ArgumentException.ThrowIfNullOrWhiteSpace(intent);

        if (Volatile.Read(ref _disposed) != 0)
        {
            return;
        }

        var message = new Dictionary<string, string>((fields?.Count ?? 0) + 1)
        {
            ["type"] = intent,
        };
        if (fields is not null)
        {
            foreach (var pair in fields)
            {
                if (!string.Equals(pair.Key, "type", StringComparison.Ordinal))
                {
                    message[pair.Key] = pair.Value;
                }
            }
        }

        var payload = JsonSerializer.Serialize(message, SerializerOptions);
        var lockTaken = false;
        try
        {
            await _writeLock.WaitAsync(_cancellation.Token).ConfigureAwait(false);
            lockTaken = true;

            // Reload after taking the lock: a disconnect may have replaced the
            // writer while this send was waiting behind another one.
            var writer = Volatile.Read(ref _writer);
            if (writer is not null)
            {
                await writer.WriteLineAsync(payload.AsMemory(), _cancellation.Token)
                    .ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (_cancellation.IsCancellationRequested)
        {
        }
        catch (IOException)
        {
            // The read loop observes the same dropped pipe and reconnects.
        }
        catch (ObjectDisposedException) when (Volatile.Read(ref _disposed) != 0)
        {
        }
        finally
        {
            if (lockTaken)
            {
                _writeLock.Release();
            }
        }
    }

    private void PublishMessage(PlayerMessage message)
    {
        // One view must not be able to terminate the pipe loop (and therefore
        // starve every other view) by throwing from its render callback.
        foreach (Action<PlayerMessage> handler in
                 MessageReceived?.GetInvocationList() ?? [])
        {
            try
            {
                handler(message);
            }
            catch (Exception)
            {
                // Rendering failures are isolated to that subscriber.
            }
        }
    }

    private void PublishConnection(bool connected)
    {
        var value = connected ? 1 : 0;
        if (Interlocked.Exchange(ref _connected, value) == value)
        {
            return;
        }

        foreach (Action<bool> handler in ConnectionChanged?.GetInvocationList() ?? [])
        {
            try
            {
                handler(connected);
            }
            catch (Exception)
            {
                // Connection observers do not own transport lifetime.
            }
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        // Cancellation interrupts connect, delay, idle reads and blocked sends.
        // The synchronization objects are intentionally left for GC: disposing
        // them while those operations unwind creates release/use-after-dispose
        // races and they allocate no OS handles unless their WaitHandle APIs are
        // explicitly requested (which this class never does).
        _cancellation.Cancel();
        Volatile.Write(ref _writer, null);
        MessageReceived = null;
        ConnectionChanged = null;
    }

    /// <summary>A buffered reader that rejects overlong lines before allocating them.</summary>
    private sealed class BoundedLineReader : IDisposable
    {
        private readonly TextReader _reader;
        private readonly int _maximumLength;
        private char[]? _buffer = ArrayPool<char>.Shared.Rent(ReadBufferCharacters);
        private int _start;
        private int _end;

        public BoundedLineReader(TextReader reader, int maximumLength)
        {
            _reader = reader;
            _maximumLength = maximumLength;
        }

        public async ValueTask<string?> ReadLineAsync(CancellationToken cancellationToken)
        {
            ObjectDisposedException.ThrowIf(_buffer is null, this);
            StringBuilder? builder = null;

            while (true)
            {
                var buffer = _buffer!;
                for (var index = _start; index < _end; index++)
                {
                    if (buffer[index] != '\n')
                    {
                        continue;
                    }

                    var count = index - _start;
                    var hasCarriageReturn = count > 0 && buffer[index - 1] == '\r';
                    var contentCount = hasCarriageReturn ? count - 1 : count;

                    // CRLF can straddle two buffer fills. In that case the CR
                    // is already in the builder when the LF is found here.
                    if (!hasCarriageReturn && builder is { Length: > 0 }
                        && builder[builder.Length - 1] == '\r')
                    {
                        builder.Length--;
                    }

                    EnsureWithinLimit((builder?.Length ?? 0) + contentCount);

                    string result;
                    if (builder is null)
                    {
                        result = new string(buffer, _start, contentCount);
                    }
                    else
                    {
                        builder.Append(buffer, _start, contentCount);
                        result = builder.ToString();
                    }

                    _start = index + 1;
                    return result;
                }

                var remaining = _end - _start;
                if (remaining > 0)
                {
                    EnsureWithinLimit((builder?.Length ?? 0) + remaining);
                    (builder ??= new StringBuilder(Math.Min(_maximumLength, remaining * 2)))
                        .Append(buffer, _start, remaining);
                }

                _start = 0;
                _end = await _reader.ReadAsync(buffer.AsMemory(), cancellationToken)
                    .ConfigureAwait(false);
                if (_end == 0)
                {
                    return builder?.ToString();
                }
            }
        }

        private void EnsureWithinLimit(int length)
        {
            if (length > _maximumLength)
            {
                throw new InvalidDataException(
                    $"Pipe message exceeds {_maximumLength} characters.");
            }
        }

        public void Dispose()
        {
            var buffer = Interlocked.Exchange(ref _buffer, null);
            if (buffer is not null)
            {
                ArrayPool<char>.Shared.Return(buffer);
            }
        }
    }
}
