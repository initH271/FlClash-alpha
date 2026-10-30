import 'package:fl_clash/common/constant.dart';
import 'package:fl_clash/common/service_probe.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/core.dart';
import 'package:fl_clash/providers/route_state.dart';
import 'package:fl_clash/providers/routed_probe.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

typedef RouteCheckTarget = ({String label, String url});

/// Edit freely: each is one HTTP(S) request routed by the current rules.
const routeCheckTargets = <RouteCheckTarget>[
  (label: 'Google', url: 'https://www.google.com/generate_204'),
  (label: 'FCM', url: 'https://fcm.googleapis.com/'),
  (label: 'GitHub', url: 'https://github.com/'),
  (label: 'OKX', url: 'https://www.okx.com/'),
  (label: 'Baidu', url: 'https://www.baidu.com/'),
];

enum RouteCheckOutcome { ok, timeout, failed }

RouteCheckOutcome routeCheckOutcomeOf(ProbeResult result) =>
    switch (result.error) {
      null when result.statusCode > 0 => RouteCheckOutcome.ok,
      'timeout' => RouteCheckOutcome.timeout,
      _ => RouteCheckOutcome.failed,
    };

final routeCheckProvider =
    NotifierProvider<
      RouteCheck,
      RoutedProbeState<RouteCheckTarget, ProbeResult>
    >(RouteCheck.new);

/// Runs only when asked; an answer the route has moved under is dropped.
class RouteCheck
    extends Notifier<RoutedProbeState<RouteCheckTarget, ProbeResult>>
    with RoutedProbe<RouteCheckTarget, ProbeResult> {
  @override
  RoutedProbeState<RouteCheckTarget, ProbeResult> build() => buildProbe();

  @override
  bool isFailure(ProbeResult value) =>
      routeCheckOutcomeOf(value) != RouteCheckOutcome.ok;

  @override
  Future<Map<RouteCheckTarget, ProbeAnswer<ProbeResult>>> probe(
    RouteCheckTarget target,
    RouteState route,
  ) async {
    final result = await ref
        .read(coreHandlerProvider)
        .probe(
          ProbeParams(
            url: target.url,
            proxyName: route.proxied ? routedOutbound : directOutbound,
            timeout: probeTimeoutDuration.inMilliseconds,
          ),
        );
    return {target: ProbeAnswer(value: result)};
  }
}
