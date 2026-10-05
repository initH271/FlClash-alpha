import 'dart:async';

class UpdateCheckScheduler {
  final Future<Map<String, dynamic>?> Function() load;
  final Future<void> Function(Map<String, dynamic>) notify;
  final DateTime Function() now;
  final void Function(Object) onError;
  final Duration interval;

  UpdateCheckScheduler({
    required this.load,
    required this.notify,
    required this.onError,
    this.now = DateTime.now,
    this.interval = const Duration(hours: 6),
  });

  Timer? _timer;
  Future<bool>? _checking;
  DateTime? _lastChecked;
  Map<String, dynamic>? _pending;
  final Set<String> _notified = {};
  bool _enabled = false;
  bool _foreground = true;
  bool _disposed = false;
  int _revision = 0;

  void setEnabled(bool enabled) {
    if (_disposed || _enabled == enabled) return;
    _enabled = enabled;
    if (!enabled) {
      _revision++;
      _pending = null;
      _lastChecked = null;
      _timer?.cancel();
    } else {
      unawaited(check());
    }
  }

  void setForeground(bool foreground) {
    if (_disposed || _foreground == foreground) return;
    _foreground = foreground;
    _timer?.cancel();
    if (foreground) unawaited(check());
  }

  Future<bool> check() {
    if (_disposed || !_enabled || !_foreground) return Future.value(false);
    if (_checking != null) return _checking!;
    final fetch = _pending == null;
    if (fetch &&
        _lastChecked != null &&
        now().difference(_lastChecked!) < interval) {
      _arm();
      return Future.value(false);
    }
    final result = Completer<bool>();
    _checking = result.future;
    unawaited(_run(_revision, fetch: fetch).then(result.complete));
    return result.future;
  }

  Future<bool> _run(int revision, {required bool fetch}) async {
    _timer?.cancel();
    try {
      if (fetch) {
        _lastChecked = now();
        final release = await load();
        if (_disposed || !_enabled || revision != _revision) return false;
        _pending = release;
      }
      final release = _pending;
      if (release == null || !_foreground) return false;
      final identity = '${release['build'] ?? release['tag_name']}';
      _pending = null;
      if (!_notified.add(identity)) return false;
      try {
        await notify(release);
      } catch (_) {
        _notified.remove(identity);
        rethrow;
      }
      return true;
    } catch (error) {
      if (!_disposed) onError(error);
      return false;
    } finally {
      _checking = null;
      if (!_disposed && _enabled && _foreground && revision != _revision) {
        scheduleMicrotask(() => unawaited(check()));
      } else {
        _arm();
      }
    }
  }

  void _arm() {
    _timer?.cancel();
    if (_disposed || !_enabled || !_foreground || _checking != null) return;
    final remaining = _lastChecked == null
        ? Duration.zero
        : interval - now().difference(_lastChecked!);
    _timer = Timer(remaining.isNegative ? Duration.zero : remaining, () {
      unawaited(check());
    });
  }

  void dispose() {
    _disposed = true;
    _revision++;
    _pending = null;
    _timer?.cancel();
  }
}
