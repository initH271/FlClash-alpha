import 'dart:async';

import 'package:url_launcher/url_launcher.dart';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/config/dns.dart';
import 'package:fl_clash/views/connection/connections.dart';
import 'package:fl_clash/views/network_features.dart';
import 'package:fl_clash/views/proxies/providers.dart';
import 'package:fl_clash/views/service_checks.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'start_button.dart';

class FeatureCard extends StatelessWidget {
  const FeatureCard({
    super.key,
    required this.label,
    required this.icon,
    this.onPressed,
    this.large = false,
    required this.child,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool large;
  final Widget child;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: getWidgetHeight(large ? 2 : 1),
    child: CommonCard(
      radius: AppCorner.lg,
      info: Info(label: label, iconData: icon),
      onPressed: onPressed,
      child: Padding(padding: baseInfoEdgeInsets, child: child),
    ),
  );
}

class NetworkSpeedSmall extends ConsumerWidget {
  const NetworkSpeedSmall({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final traffic = ref.watch(trafficsProvider).list.safeLast(const Traffic());
    return FeatureCard(
      label: context.appLocalizations.speedStatistics,
      icon: Icons.speed,
      child: Text(traffic.speedText, style: context.textTheme.titleLarge),
    );
  }
}

enum FeatureSwitchKind { ipv6, wake, dns, sniffer, ntp }

class FeatureSwitchCard extends ConsumerWidget {
  const FeatureSwitchCard({super.key, required this.kind});
  final FeatureSwitchKind kind;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = context.appLocalizations;
    final settings = ref.watch(networkFeaturesProvider);
    final (label, icon, enabled) = switch (kind) {
      FeatureSwitchKind.ipv6 => (
        'IPv6',
        Icons.public,
        ref.watch(patchClashConfigProvider).ipv6,
      ),
      FeatureSwitchKind.wake => (
        l.keepAwake,
        Icons.light_mode,
        settings.keepAwake,
      ),
      FeatureSwitchKind.dns => (
        l.dnsOverride,
        Icons.dns,
        ref.watch(overrideDnsProvider),
      ),
      FeatureSwitchKind.sniffer => (
        l.snifferOverride,
        Icons.manage_search,
        settings.overrideSniffer,
      ),
      FeatureSwitchKind.ntp => (
        l.ntpOverride,
        Icons.access_time,
        settings.overrideNtp,
      ),
    };
    void change(bool value) {
      switch (kind) {
        case FeatureSwitchKind.ipv6:
          ref
              .read(patchClashConfigProvider.notifier)
              .update((s) => s.copyWith(ipv6: value));
          ref
              .read(vpnSettingProvider.notifier)
              .update((s) => s.copyWith(ipv6: value));
        case FeatureSwitchKind.dns:
          ref.read(overrideDnsProvider.notifier).value = value;
        case FeatureSwitchKind.wake:
          ref
              .read(networkFeaturesProvider.notifier)
              .update((s) => s.copyWith(keepAwake: value));
        case FeatureSwitchKind.sniffer:
          ref
              .read(networkFeaturesProvider.notifier)
              .update((s) => s.copyWith(overrideSniffer: value));
        case FeatureSwitchKind.ntp:
          ref
              .read(networkFeaturesProvider.notifier)
              .update((s) => s.copyWith(overrideNtp: value));
      }
    }

    return FeatureCard(
      label: label,
      icon: icon,
      onPressed: () {
        if (kind == FeatureSwitchKind.dns) {
          showSheet(
            context: context,
            builder: (_) =>
                AdaptiveSheetScaffold(title: label, body: const DnsListView()),
          );
        } else {
          NetworkFeaturesView.show(context);
        }
      },
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Flexible(child: Text(enabled ? l.featureEnabled : l.featureDisabled)),
          Switch(value: enabled, onChanged: change),
        ],
      ),
    );
  }
}

class ConnectionStatusCard extends ConsumerStatefulWidget {
  const ConnectionStatusCard({super.key, this.fcm = false});
  final bool fcm;

  @override
  ConsumerState<ConnectionStatusCard> createState() =>
      _ConnectionStatusCardState();
}

class _ConnectionStatusCardState extends ConsumerState<ConnectionStatusCard>
    with WidgetsBindingObserver, ActivePollingMixin<ConnectionStatusCard> {
  List<TrackerInfo>? _connections;

  @override
  Duration get pollInterval => const Duration(seconds: 3);

  @override
  Future<void> poll(PollGuard isCurrent) async {
    try {
      final value = ref.read(coreStatusProvider) == CoreStatus.connected
          ? await ref.read(coreHandlerProvider).getConnections()
          : <TrackerInfo>[];
      if (isCurrent()) setState(() => _connections = value);
    } catch (error) {
      if (isCurrent()) setState(() => _connections = null);
      commonPrint.log(
        'Connection dashboard: $error',
        logLevel: LogLevel.warning,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = context.appLocalizations;
    final connections = _connections;
    final fcm = connections?.any((connection) {
      final metadata = connection.metadata;
      return const {
            '5228',
            '5229',
            '5230',
          }.contains(metadata.destinationPort) &&
          (metadata.host.endsWith('.google.com') ||
              metadata.host.endsWith('.googleapis.com') ||
              metadata.process.contains('com.google.android.gms') ||
              metadata.processPath.contains('com.google.android.gms'));
    });
    return FeatureCard(
      label: widget.fcm ? 'FCM' : l.connectionsCount,
      icon: widget.fcm ? Icons.notifications_active : Icons.hub,
      onPressed: () =>
          showSheet(context: context, builder: (_) => const ConnectionsView()),
      child: Text(
        widget.fcm
            ? (fcm == null
                  ? l.serviceUnknown
                  : fcm
                  ? l.fcmConnected
                  : l.fcmDisconnected)
            : connections?.length.toString() ?? '—',
        style: context.textTheme.titleMedium,
      ),
    );
  }
}

class ProvidersInfo extends StatelessWidget {
  const ProvidersInfo({super.key});

  @override
  Widget build(BuildContext context) => FeatureCard(
    label: context.appLocalizations.providersInfo,
    icon: Icons.storage,
    onPressed: () =>
        showSheet(context: context, builder: (_) => const ProvidersView()),
    child: Text(context.appLocalizations.providers),
  );
}

class OnlinePanel extends ConsumerWidget {
  const OnlinePanel({super.key});

  Future<void> _open(BuildContext context, WidgetRef ref) async {
    if (ref.read(patchClashConfigProvider).externalController ==
        ExternalControllerStatus.close) {
      final accepted = await dialogs.showMessage(
        title: context.appLocalizations.onlinePanel,
        message: TextSpan(
          text: context.appLocalizations.onlinePanelEnablePrompt,
        ),
      );
      if (accepted != true || !context.mounted) return;
      ref
          .read(patchClashConfigProvider.notifier)
          .update(
            (state) => state.copyWith(
              externalController: ExternalControllerStatus.open,
            ),
          );
      final ready = await ref.read(setupActionProvider.notifier).fullSetup();
      if (!ready || !context.mounted) return;
    }
    await launchUrl(
      Uri.parse('http://127.0.0.1:9090/ui/'),
      mode: LaunchMode.externalApplication,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) => FeatureCard(
    label: context.appLocalizations.onlinePanel,
    icon: Icons.dashboard,
    onPressed: () => unawaited(_open(context, ref)),
    child: Text(
      ref.watch(patchClashConfigProvider).externalController ==
              ExternalControllerStatus.open
          ? context.appLocalizations.featureEnabled
          : context.appLocalizations.featureDisabled,
    ),
  );
}

class MediaUnlockCard extends ConsumerWidget {
  const MediaUnlockCard({super.key, this.small = false});
  final bool small;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = ref.watch(serviceCheckResultsProvider);
    final available = results.values
        .where((r) => r.status == MediaUnlockStatus.unlocked)
        .length;
    return FeatureCard(
      label: context.appLocalizations.serviceChecks,
      icon: Icons.travel_explore,
      large: !small,
      onPressed: () => showServiceChecks(context),
      child: Text(
        results.isEmpty
            ? context.appLocalizations.serviceUnknown
            : '$available / ${results.length}',
        style: context.textTheme.titleLarge,
      ),
    );
  }
}

class DashboardStartCard extends StatelessWidget {
  const DashboardStartCard({super.key});

  @override
  Widget build(BuildContext context) => SizedBox(
    height: getWidgetHeight(1),
    child: const Center(child: StartButton()),
  );
}
