import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void showServiceChecks(BuildContext context) {
  showSheet(
    context: context,
    builder: (_) => AdaptiveSheetScaffold(
      title: context.appLocalizations.serviceChecks,
      body: const ServiceChecksView(),
    ),
  );
}

String serviceStatusText(BuildContext context, MediaUnlockStatus status) {
  final l = context.appLocalizations;
  return switch (status) {
    MediaUnlockStatus.unlocked => l.serviceAvailable,
    MediaUnlockStatus.limited => l.serviceLimited,
    MediaUnlockStatus.flagged => l.serviceFlagged,
    MediaUnlockStatus.blocked => l.serviceBlocked,
    MediaUnlockStatus.failed => l.serviceFailed,
    MediaUnlockStatus.testing => l.serviceTesting,
    MediaUnlockStatus.unknown => l.serviceUnknown,
  };
}

class ServiceChecksView extends ConsumerStatefulWidget {
  const ServiceChecksView({super.key, this.checker});
  final MediaUnlockChecker? checker;

  @override
  ConsumerState<ServiceChecksView> createState() => _ServiceChecksViewState();
}

class _ServiceChecksViewState extends ConsumerState<ServiceChecksView> {
  late final MediaUnlockChecker _checker;
  final _selected = <MediaPlatform>{
    MediaPlatform.openai,
    MediaPlatform.claude,
    MediaPlatform.gemini,
    MediaPlatform.netflix,
    MediaPlatform.disney,
    MediaPlatform.youtube,
    MediaPlatform.spotify,
  };
  bool _running = false;
  int _revision = 0;

  @override
  void initState() {
    super.initState();
    _checker =
        widget.checker ??
        MediaUnlockChecker(
          unifiedDelay: ref.read(patchClashConfigProvider).unifiedDelay,
        );
    ref.listenManual(selectedMapProvider, (_, _) => _routeChanged());
    ref.listenManual(currentProfileIdProvider, (_, _) => _routeChanged());
    ref.listenManual(
      runTimeProvider.select((value) => value != null),
      (_, _) => _routeChanged(),
    );
  }

  void _routeChanged() {
    _revision++;
    _checker.cancel();
    ref.read(serviceCheckResultsProvider.notifier).clear();
    if (mounted && _running) setState(() => _running = false);
  }

  Future<void> _check() async {
    if (_running) {
      _revision++;
      _checker.cancel();
      setState(() => _running = false);
      return;
    }
    if (_selected.isEmpty) return;
    final revision = ++_revision;
    setState(() => _running = true);
    try {
      await _checker.checkAll(
        platforms: _selected.toList(),
        onProgress: (result) {
          if (mounted && revision == _revision) {
            ref.read(serviceCheckResultsProvider.notifier).add(result);
          }
        },
      );
    } finally {
      if (mounted && revision == _revision) setState(() => _running = false);
    }
  }

  @override
  void dispose() {
    _revision++;
    _checker.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = context.appLocalizations;
    final results = ref.watch(serviceCheckResultsProvider);
    return Column(
      children: [
        Padding(padding: baseInfoEdgeInsets, child: Text(l.serviceCheckDesc)),
        Padding(
          padding: baseInfoEdgeInsets,
          child: Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  key: const ValueKey('run-service-checks'),
                  onPressed: _selected.isEmpty && !_running ? null : _check,
                  icon: Icon(_running ? Icons.stop : Icons.refresh),
                  label: Text(_running ? l.cancel : l.serviceChecks),
                ),
              ),
            ],
          ),
        ),
        if (_running) const LinearProgressIndicator(),
        Expanded(
          child: ListView.builder(
            itemCount: MediaPlatform.values.length,
            itemBuilder: (_, index) {
              final platform = MediaPlatform.values[index];
              final result = results[platform];
              final status = result?.status ?? MediaUnlockStatus.unknown;
              return CheckboxListTile(
                value: _selected.contains(platform),
                onChanged: _running
                    ? null
                    : (value) => setState(() {
                        value == true
                            ? _selected.add(platform)
                            : _selected.remove(platform);
                      }),
                title: Text(platform.defaultName),
                subtitle: Text(
                  [
                    serviceStatusText(context, status),
                    if (result?.region != null) result!.region!,
                    if (result?.latency != null) '${result!.latency} ms',
                  ].join(' · '),
                ),
                secondary: Icon(
                  Icons.public,
                  color: status.statusColor(context.colorScheme),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
