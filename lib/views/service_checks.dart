import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'service_check_settings.dart';
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
  const ServiceChecksView({super.key});

  @override
  ConsumerState<ServiceChecksView> createState() => _ServiceChecksViewState();
}

class _ServiceChecksViewState extends ConsumerState<ServiceChecksView> {
  late final ServiceCheckController _controller;

  @override
  void initState() {
    super.initState();
    _controller = ref.read(serviceCheckControllerProvider.notifier);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _controller.panelOpened();
    });
  }

  @override
  void dispose() {
    _controller.panelClosed();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l = context.appLocalizations;
    final results = ref.watch(serviceCheckResultsProvider);
    final activity = ref.watch(serviceCheckControllerProvider);
    final selected = ref.watch(
      networkFeaturesProvider.select((value) => value.serviceChecks.platforms),
    );
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
                  onPressed: selected.isEmpty && !activity.running
                      ? null
                      : _controller.toggleManual,
                  icon: Icon(activity.running ? Icons.stop : Icons.refresh),
                  label: Text(activity.running ? l.cancel : l.serviceChecks),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                key: const ValueKey('service-check-options'),
                tooltip: l.autoServiceChecks,
                icon: const Icon(Icons.tune),
                onPressed: () => ServiceCheckSettingsView.show(context),
              ),
            ],
          ),
        ),
        if (activity.running) const LinearProgressIndicator(),
        if (activity.failed)
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
                    value: selected.contains(platform),
                    onChanged: activity.running
                        ? null
                        : (value) {
                            final next = selected.toSet();
                            value == true
                                ? next.add(platform)
                                : next.remove(platform);
                            ref
                                .read(networkFeaturesProvider.notifier)
                                .update(
                                  (settings) => settings.copyWith(
                                    serviceChecks: settings.serviceChecks
                                        .copyWith(platforms: next.toList()),
                                  ),
                                );
                          },
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
