import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ServiceCheckSettingsView extends ConsumerWidget {
  const ServiceCheckSettingsView({super.key});

  static void show(BuildContext context) {
    showSheet(
      context: context,
      props: const SheetProps(isScrollControlled: true),
      builder: (_) => AdaptiveSheetScaffold(
        title: context.appLocalizations.autoServiceChecks,
        body: const ServiceCheckSettingsView(),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = context.appLocalizations;
    final settings = ref.watch(
      networkFeaturesProvider.select((value) => value.serviceChecks),
    );
    void update(ServiceCheckSettings Function(ServiceCheckSettings) change) {
      ref
          .read(networkFeaturesProvider.notifier)
          .update(
            (value) =>
                value.copyWith(serviceChecks: change(value.serviceChecks)),
          );
    }

    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        Padding(
          padding: baseInfoEdgeInsets,
          child: Text(l.autoServiceChecksDesc),
        ),
        ContentSection(
          title: l.autoServiceChecks,
          children: [
            SwitchListTile(
              key: const ValueKey('service-check-on-connect'),
              title: Text(l.serviceCheckOnConnect),
              subtitle: Text(l.serviceCheckOnConnectDesc),
              value: settings.onConnect,
              onChanged: (value) => update((s) => s.copyWith(onConnect: value)),
            ),
            SwitchListTile(
              key: const ValueKey('service-check-on-route'),
              title: Text(l.serviceCheckOnRouteChange),
              subtitle: Text(l.serviceCheckOnRouteChangeDesc),
              value: settings.onRouteChange,
              onChanged: (value) =>
                  update((s) => s.copyWith(onRouteChange: value)),
            ),
            SwitchListTile(
              key: const ValueKey('service-check-on-panel'),
              title: Text(l.serviceCheckOnPanelOpen),
              subtitle: Text(l.serviceCheckOnPanelOpenDesc),
              value: settings.onPanelOpen,
              onChanged: (value) =>
                  update((s) => s.copyWith(onPanelOpen: value)),
            ),
            SwitchListTile(
              key: const ValueKey('service-check-periodic'),
              title: Text(l.serviceCheckPeriodic),
              subtitle: Text(l.serviceCheckPeriodicDesc),
              value: settings.periodic,
              onChanged: (value) => update((s) => s.copyWith(periodic: value)),
            ),
          ],
        ),
        ContentSection(
          title: l.settings,
          children: [
            ListItem<int>.options(
              key: const ValueKey('service-check-interval'),
              title: Text(l.serviceCheckInterval),
              subtitle: Text(l.serviceCheckMinutes(settings.intervalMinutes)),
              dialogTitle: l.serviceCheckInterval,
              options: ({5, 15, 30, 60, settings.intervalMinutes}.toList()
                ..sort()),
              value: settings.intervalMinutes,
              textBuilder: l.serviceCheckMinutes,
              onChanged: (value) {
                if (value != null) {
                  update((s) => s.copyWith(intervalMinutes: value));
                }
              },
            ),
            ListItem<int>.options(
              key: const ValueKey('service-check-cache'),
              title: Text(l.serviceCheckCacheLifetime),
              subtitle: Text(l.serviceCheckMinutes(settings.cacheMinutes)),
              dialogTitle: l.serviceCheckCacheLifetime,
              options: ({5, 10, 15, 30, 60, settings.cacheMinutes}.toList()
                ..sort()),
              value: settings.cacheMinutes,
              textBuilder: l.serviceCheckMinutes,
              onChanged: (value) {
                if (value != null) {
                  update((s) => s.copyWith(cacheMinutes: value));
                }
              },
            ),
          ],
        ),
      ],
    );
  }
}
