import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void showServiceChecks(BuildContext context) {
  showSheet(
    context: context,
    props: const SheetProps(isScrollControlled: true),
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
  bool _failed = false;
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
    if (mounted) {
      setState(() {
        _running = false;
        _failed = false;
      });
    }
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
    setState(() {
      _running = true;
      _failed = false;
    });
    try {
      await _checker.checkAll(
        platforms: _selected.toList(),
        onProgress: (result) {
          if (mounted && revision == _revision) {
            ref.read(serviceCheckResultsProvider.notifier).add(result);
          }
        },
      );
    } catch (error) {
      commonPrint.log(
        'Service checks failed (${error.runtimeType})',
        logLevel: LogLevel.warning,
      );
      if (mounted && revision == _revision) setState(() => _failed = true);
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
        if (_failed)
          Padding(
            padding: baseInfoEdgeInsets.copyWith(top: 0),
            child: Text(
              l.serviceCheckFailed,
              key: const ValueKey('service-check-error'),
              style: context.textTheme.bodyMedium?.copyWith(
                color: context.colorScheme.error,
              ),
            ),
          ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            itemCount: MediaPlatform.values.length,
            itemBuilder: (_, index) {
              final platform = MediaPlatform.values[index];
              final result = results[platform];
              final status = result?.status ?? MediaUnlockStatus.unknown;
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: ContentPanel(
                  child: CheckboxListTile(
                    value: _selected.contains(platform),
                    onChanged: _running
                        ? null
                        : (value) => setState(() {
                            value == true
                                ? _selected.add(platform)
                                : _selected.remove(platform);
                          }),
                    title: Text(
                      platform.defaultName,
                      style: context.textTheme.bodyLarge?.copyWith(
                        color: context.colorScheme.onSurface,
                      ),
                    ),
                    subtitle: Text(
                      [
                        serviceStatusText(context, status),
                        if (result?.region != null) result!.region!,
                        if (result?.latency != null)
                          '${result!.latency}\u00a0ms',
                      ].join(' · '),
                      style: context.textTheme.bodyMedium?.copyWith(
                        color: context.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    secondary: Icon(
                      Icons.public,
                      color: status.statusColor(context.colorScheme),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}
