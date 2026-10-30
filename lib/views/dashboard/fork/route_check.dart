import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/service_probe.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/fork/route_check.dart';
import 'package:fl_clash/providers/outbound_ip.dart';
import 'package:fl_clash/providers/routed_probe.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/dashboard/style.dart';
import 'package:fl_clash/views/dashboard/widgets/card.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

class RouteCheckCard extends ConsumerStatefulWidget {
  const RouteCheckCard({super.key});

  @override
  ConsumerState<RouteCheckCard> createState() => _RouteCheckCardState();
}

class _RouteCheckCardState extends ConsumerState<RouteCheckCard> {
  late final OutboundIpProbe _ips;

  @override
  void initState() {
    super.initState();
    _ips = ref.read(outboundIpProbeProvider.notifier)..watch(routedOutbound);
  }

  @override
  void dispose() {
    _ips.unwatch(routedOutbound);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    final state = ref.watch(routeCheckProvider);
    final ip = ref.watch(
      outboundIpProbeProvider.select((state) => state.valueOf(routedOutbound)),
    );
    final node = [for (final target in routeCheckTargets) state.valueOf(target)]
        .nonNulls
        .map((result) => result.chains.firstOrNull)
        .nonNulls
        .firstWhere((exit) => exit != directOutbound, orElse: () => '');
    final loading = routeCheckTargets.any(state.isLoading);
    final exit = [
      if (ip != null) '${ip.countryCode.countryFlagEmoji} ${ip.ip}',
      if (node.isNotEmpty) node,
    ].join(' · ').trim();
    return DashboardCard(
      semanticLabel: appLocalizations.forkRouteCheck,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 8,
        children: [
          DashboardCardHeader(
            glyph: AppGlyphs.target,
            title: appLocalizations.forkRouteCheck,
            trailing: [
              if (loading)
                const SizedBox.square(
                  dimension: DashboardIconButton.size,
                  child: Center(child: CommonCircleLoading(size: 18)),
                )
              else
                DashboardIconButton(
                  glyph: AppGlyphs.bolt,
                  tooltip: appLocalizations.forkRouteCheckRun,
                  onPressed: () => ref
                      .read(routeCheckProvider.notifier)
                      .refresh(routeCheckTargets),
                ),
            ],
          ),
          Text(
            '${appLocalizations.outboundIp}  ${exit.isEmpty ? '—' : exit}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: DashboardText.label(context),
          ),
          for (final target in routeCheckTargets)
            _TargetRow(target: target, entry: state.entryOf(target)),
          Text(
            appLocalizations.forkRouteCheckHint,
            style: DashboardText.label(context),
          ),
        ],
      ),
    );
  }
}

class _TargetRow extends StatelessWidget {
  const _TargetRow({required this.target, required this.entry});

  final RouteCheckTarget target;
  final ProbeEntry<ProbeResult> entry;

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    final colors = DashboardColors.of(context);
    final result = entry.isLoading ? null : entry.value;
    final outcome = result == null ? null : routeCheckOutcomeOf(result);
    final failed =
        entry.phase == ProbePhase.failed && outcome != RouteCheckOutcome.ok;
    final Widget status = switch ((entry.phase, outcome)) {
      (ProbePhase.probing, _) => const CommonCircleLoading(size: 14),
      (_, RouteCheckOutcome.ok) => Text('${result!.delay} ms'),
      (_, RouteCheckOutcome.timeout) => Text(appLocalizations.timeout),
      _ when failed => Text(appLocalizations.serviceFailed),
      _ => Text(appLocalizations.forkRouteCheckIdle),
    };
    final route = result == null
        ? ''
        : [
            [
              result.rule,
              result.rulePayload,
            ].where((s) => s.isNotEmpty).join(' '),
            result.chains.reversed.join(' › '),
          ].where((part) => part.isNotEmpty).join(' · ');
    return DashboardBlock(
      radius: DashboardCorner.mobileBlock,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 2,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  target.label,
                  style: DashboardText.rowTitle(context),
                ),
              ),
              DefaultTextStyle.merge(
                style: DashboardText.label(
                  context,
                  color: failed ? colors.warn : null,
                ),
                child: status,
              ),
            ],
          ),
          if (route.isNotEmpty)
            Text(
              route,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: DashboardText.label(context),
            ),
        ],
      ),
    );
  }
}
