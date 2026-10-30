import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/dashboard/style.dart';
import 'package:fl_clash/views/dashboard/widgets/card.dart';
import 'package:fl_clash/views/dashboard/widgets/connections_table.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

const _pushPorts = {'5228', '5229', '5230'};
const _unproxiedExits = {'', 'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS'};
const _maxRows = 3;

/// FCM holds one long-lived connection to mtalk.google.com or alt*-mtalk.
final _pushHost = RegExp(r'(^|[.-])mtalk\d*\.google\.com$');

bool isPushConnection(TrackerInfo info) =>
    _pushPorts.contains(info.metadata.destinationPort) ||
    _pushHost.hasMatch(info.metadata.host.toLowerCase());

bool isProxiedConnection(TrackerInfo info) =>
    !_unproxiedExits.contains(info.chains.firstOrNull ?? '');

class PushChannelCard extends ConsumerStatefulWidget {
  const PushChannelCard({super.key});

  @override
  ConsumerState<PushChannelCard> createState() => _PushChannelCardState();
}

class _PushChannelCardState extends ConsumerState<PushChannelCard>
    with
        WidgetsBindingObserver,
        ActivePollingMixin<PushChannelCard>,
        RouteMotionHoldMixin<PushChannelCard>,
        ConnectionsPolling<PushChannelCard> {
  @override
  bool get pollsConnections => true;

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    final push = connections.where(isPushConnection).toList();
    final unproxied = push.where((info) => !isProxiedConnection(info));
    final verdict = push.isEmpty
        ? null
        : unproxied.isNotEmpty
        ? DashboardChip(
            label: appLocalizations.forkPushDirect,
            tone: DashboardChipTone.warn,
          )
        : DashboardChip(
            label: appLocalizations.forkPushViaProxy,
            tone: DashboardChipTone.ok,
          );
    return DashboardCard(
      semanticLabel: appLocalizations.forkPushChannel,
      onTap: () => openDashboardFeed(context, DashboardFeed.connections),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 8,
        children: [
          DashboardCardHeader(
            glyph: AppGlyphs.send,
            title: appLocalizations.forkPushChannel,
            chevron: true,
            trailing: [?verdict],
          ),
          const SizedBox(height: 4),
          if (push.isEmpty)
            const _EmptyPush()
          else ...[
            for (final info in push.take(_maxRows)) _PushRow(info),
            if (push.length > _maxRows)
              Text(
                '+${push.length - _maxRows}',
                style: DashboardText.label(context),
              ),
          ],
        ],
      ),
    );
  }
}

class _EmptyPush extends StatelessWidget {
  const _EmptyPush();

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 2,
      children: [
        Text(
          appLocalizations.forkPushEmpty,
          style: DashboardText.rowTitle(context),
        ),
        Text(
          appLocalizations.forkPushEmptyHint,
          style: DashboardText.label(context),
        ),
      ],
    );
  }
}

class _PushRow extends StatelessWidget {
  const _PushRow(this.info);

  final TrackerInfo info;

  @override
  Widget build(BuildContext context) {
    final metadata = info.metadata;
    final host = metadata.host.isNotEmpty
        ? metadata.host
        : metadata.destinationIP;
    final rule = [
      info.rule,
      info.rulePayload,
    ].where((part) => part.isNotEmpty).join(' ');
    final chain = info.chains.reversed.join(' › ');
    final proxied = isProxiedConnection(info);
    final colors = DashboardColors.of(context);
    return DashboardBlock(
      radius: DashboardCorner.mobileBlock,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        spacing: 2,
        children: [
          Text(
            '$host:${metadata.destinationPort}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: DashboardText.rowTitle(context),
          ),
          Text(
            [rule, chain].where((part) => part.isNotEmpty).join(' · '),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: DashboardText.label(
              context,
              color: proxied ? null : colors.warn,
            ),
          ),
        ],
      ),
    );
  }
}
