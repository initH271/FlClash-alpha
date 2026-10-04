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
    this.contentPadding,
    required this.child,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool large;
  final EdgeInsets? contentPadding;
  final Widget child;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: getWidgetHeight(large ? 2 : 1),
    child: CommonCard(
      radius: AppCorner.lg,
      onPressed: onPressed,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InfoHeader(
            padding: baseInfoEdgeInsets.copyWith(bottom: 0),
            info: Info(label: label, iconData: icon),
          ),
          Expanded(
            child: Padding(
              padding:
                  contentPadding ??
                  baseInfoEdgeInsets.copyWith(top: 4, bottom: 8),
              child: Align(alignment: Alignment.centerLeft, child: child),
            ),
          ),
        ],
      ),
    ),
  );
}

class NetworkSpeedSmall extends ConsumerWidget {
  const NetworkSpeedSmall({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final traffics = ref.watch(trafficsProvider).list;
    final traffic = traffics.safeLast(const Traffic());
    final points = [
      const Point(0, 0),
      const Point(1, 0),
      for (var i = 0; i < traffics.length; i++)
        Point((i + 2).toDouble(), traffics[i].speed.toDouble()),
    ];
    return SizedBox(
      height: getWidgetHeight(1),
      child: CommonCard(
        radius: AppCorner.lg,
        child: Column(
          children: [
            LayoutBuilder(
              builder: (context, constraints) => Padding(
                padding: baseInfoEdgeInsets.copyWith(bottom: 0),
                child: Row(
                  children: [
                    const Icon(Icons.speed, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Tooltip(
                        message: traffic.speedText,
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.centerLeft,
                          child: Text(
                            constraints.maxWidth < 200
                                ? '${traffic.speed.traffic.show}/s'
                                : '${traffic.up.traffic.show}↑ ${traffic.down.traffic.show}↓',
                            style: context.textTheme.titleSmall,
                            maxLines: 1,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: LineChart(
                  gradient: true,
                  color: context.colorScheme.primary,
                  points: points,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 2, 12, 8),
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  '↑ ${traffic.up.traffic.show}/s   ↓ ${traffic.down.traffic.show}/s',
                  style: context.textTheme.labelSmall?.copyWith(
                    color: context.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
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
      contentPadding: baseInfoEdgeInsets.copyWith(top: 4, bottom: 8, right: 8),
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
          Flexible(
            child: TooltipText(
              text: Text(
                enabled ? l.featureOnShort : l.featureOffShort,
                style: context.textTheme.titleSmall,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
          Switch(
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            value: enabled,
            onChanged: change,
          ),
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
      child: !widget.fcm
          ? Row(
              children: [
                Expanded(
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      connections?.length.toString() ?? '—',
                      style: context.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
                    ),
                  ),
                ),
                Flexible(
                  flex: 2,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        for (final protocol in ['TCP', 'UDP'])
                          Padding(
                            padding: const EdgeInsets.only(left: 12),
                            child: Text(
                              '$protocol  ${connections == null ? '—' : connections.where((connection) => connection.metadata.network.toUpperCase() == protocol).length}',
                              style: context.textTheme.bodySmall?.copyWith(
                                color: context.colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            )
          : Text(
              widget.fcm
                  ? (fcm == null
                        ? l.serviceUnknown
                        : fcm
                        ? l.fcmConnected
                        : l.fcmDisconnected)
                  : connections?.length.toString() ?? '—',
              style: widget.fcm
                  ? context.textTheme.bodyMedium
                  : context.textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w600,
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
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
    child: Text(
      context.appLocalizations.providers,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
    ),
  );
}

class OnlinePanel extends ConsumerStatefulWidget {
  const OnlinePanel({super.key});

  @override
  ConsumerState<OnlinePanel> createState() => _OnlinePanelState();
}

class _OnlinePanelState extends ConsumerState<OnlinePanel> {
  bool _opening = false;
  bool _needsSetup = false;
  bool _failed = false;

  Future<void> _open() async {
    if (_opening) return;
    setState(() {
      _opening = true;
      _failed = false;
    });
    try {
      if (ref.read(patchClashConfigProvider).externalController ==
          ExternalControllerStatus.close) {
        final accepted = await dialogs.showMessage(
          context: context,
          title: context.appLocalizations.onlinePanel,
          message: TextSpan(
            text: context.appLocalizations.onlinePanelEnablePrompt,
          ),
        );
        if (accepted != true || !mounted) return;
        _needsSetup = true;
        ref
            .read(patchClashConfigProvider.notifier)
            .update(
              (state) => state.copyWith(
                externalController: ExternalControllerStatus.open,
              ),
            );
      }
      if (_needsSetup) {
        final ready = await ref.read(setupActionProvider.notifier).fullSetup();
        if (!mounted) return;
        if (!ready) {
          setState(() => _failed = true);
          return;
        }
        _needsSetup = false;
      }
      if (!mounted ||
          ref.read(patchClashConfigProvider).externalController ==
              ExternalControllerStatus.close) {
        return;
      }
      final opened = await launchUrl(
        Uri.parse('http://127.0.0.1:9090/ui/'),
        mode: LaunchMode.externalApplication,
      );
      if (mounted && !opened) setState(() => _failed = true);
    } catch (error) {
      commonPrint.log(
        'Online panel failed (${error.runtimeType})',
        logLevel: LogLevel.warning,
      );
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _opening = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = ref.watch(patchClashConfigProvider).externalController;
    return FeatureCard(
      label: context.appLocalizations.onlinePanel,
      icon: Icons.dashboard,
      onPressed: _opening ? null : () => unawaited(_open()),
      child: TooltipText(
        text: Text(
          _opening
              ? context.appLocalizations.panelOpening
              : _failed
              ? context.appLocalizations.panelOpenFailed
              : controller == ExternalControllerStatus.open
              ? context.appLocalizations.featureEnabled
              : context.appLocalizations.featureDisabled,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: _failed
              ? context.textTheme.bodySmall?.copyWith(
                  color: context.colorScheme.error,
                )
              : null,
        ),
      ),
    );
  }
}

class MediaUnlockCard extends ConsumerWidget {
  const MediaUnlockCard({super.key, this.small = false});
  final bool small;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = ref.watch(serviceCheckResultsProvider);
    final platforms = results.isEmpty
        ? const [
            MediaPlatform.openai,
            MediaPlatform.claude,
            MediaPlatform.gemini,
            MediaPlatform.netflix,
          ]
        : results.keys.take(4).toList();
    return FeatureCard(
      label: context.appLocalizations.serviceChecks,
      icon: Icons.travel_explore,
      large: true,
      onPressed: () => showServiceChecks(context),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          for (final platform in platforms)
            _ServiceStatusRow(
              platform: platform,
              result: results[platform],
              compact: small,
            ),
        ],
      ),
    );
  }
}

class _ServiceStatusRow extends StatelessWidget {
  const _ServiceStatusRow({
    required this.platform,
    required this.result,
    required this.compact,
  });

  final MediaPlatform platform;
  final MediaUnlockResult? result;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final status = result?.status ?? MediaUnlockStatus.unknown;
    final region = result?.region;
    final label = [
      serviceStatusText(context, status),
      if (region != null && region.isNotEmpty) region,
    ].join(' · ');
    final icon = switch (status) {
      MediaUnlockStatus.unlocked => Icons.check_circle_outline,
      MediaUnlockStatus.limited ||
      MediaUnlockStatus.flagged => Icons.warning_amber_rounded,
      MediaUnlockStatus.blocked => Icons.block,
      MediaUnlockStatus.failed => Icons.error_outline,
      MediaUnlockStatus.testing => Icons.pending_outlined,
      MediaUnlockStatus.unknown => Icons.help_outline,
    };
    return Semantics(
      label: '${platform.defaultName}: $label',
      excludeSemantics: true,
      child: Tooltip(
        message: '${platform.defaultName}: $label',
        child: Row(
          children: [
            Expanded(
              child: Text(
                platform.defaultName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.textTheme.bodyMedium,
              ),
            ),
            const SizedBox(width: 8),
            Flexible(
              child: TonalStatusLabel(
                label: compact ? region ?? label : label,
                compact: compact && region == null,
                icon: icon,
                color: status.statusColor(context.colorScheme),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class DashboardStartCard extends ConsumerWidget {
  const DashboardStartCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(coreStatusProvider);
    final runTime = ref.watch(runTimeProvider);
    final l = context.appLocalizations;
    final label = switch (status) {
      CoreStatus.connected => l.connected,
      CoreStatus.connecting => l.connecting,
      CoreStatus.disconnected => l.disconnected,
    };
    return SizedBox(
      height: getWidgetHeight(1),
      child: ContentPanel(
        selected: status == CoreStatus.connected,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              const SizedBox(
                width: 44,
                height: 48,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: StartButton(maxWidth: 56, compact: true),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.textTheme.labelLarge?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      runTime != null ? getTimeText(runTime) : l.start,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.textTheme.bodySmall?.copyWith(
                        color: context.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
