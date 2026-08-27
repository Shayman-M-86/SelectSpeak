# Changelog

## Unreleased

## 0.1.3 - 2026-08-27

### Added

- A new Windows-native player and Settings window for choosing voices, clipboard behaviour, auto-hide, diagnostics, and both keyboard shortcuts.
- Supertonic voices now offer selectable speaking styles.

### Improved

- Shortcut conflicts and voice failures now show clearer explanations without losing the existing setting.
- Screen-capture selection follows the pointer more smoothly.
- Natural Voice now supports a wider range of older Windows voice packages.
- Speaking a selection in Visual Studio Code and other Electron-based applications now works reliably. Previously the copy could fail to reach SelectSpeak, leaving the selection unspoken and the clipboard replaced.
- Wrapped text no longer gains a pause at the end of every line, so prose copied from comments, docstrings, and commit messages is read as continuous sentences instead of stopping mid-thought.
- When a selection cannot be read, SelectSpeak now reports that it could not be captured instead of speaking whatever was previously on the clipboard.
- Playback is smoother and starts more responsively, and the clipboard is restored more reliably after a selection is read.

### Important changes

- The player now requires the .NET 8 Desktop Runtime and Windows App Runtime 1.8. Setup installs compatible missing runtimes system-wide.
- The older SAPI speech option has been retired in favour of Windows Natural Voice. Existing settings that selected SAPI are moved to Natural Voice automatically.
