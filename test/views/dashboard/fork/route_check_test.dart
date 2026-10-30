import 'dart:async';

import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/fork/route_check.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/dashboard/fork/route_check.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/glyph_finders.dart';
import '../../../helpers/test_app.dart';

class _MockCore extends Mock implements CoreHandlerInterface {}

const _google = ProbeResult(
  statusCode: 204,
  delay: 85,
  chains: ['HK 01', 'Proxy'],
  rule: 'DomainSuffix',
  rulePayload: 'google.com',
);

void main() {
  setUpAll(() {
    registerFallbackValue(const ProbeParams(url: '', timeout: 0));
    registerFallbackValue(const OutboundIpParams(timeout: 0));
  });

  late _MockCore core;
  late Map<String, Completer<ProbeResult?>> pending;
  late List<ProbeParams> asked;

  setUp(() {
    core = _MockCore();
    pending = {};
    asked = [];
    when(() => core.probe(any())).thenAnswer((invocation) {
      final params = invocation.positionalArguments.single as ProbeParams;
      asked.add(params);
      return (pending[params.url] = Completer<ProbeResult?>()).future;
    });
    when(() => core.outboundIp(any())).thenAnswer(
      (_) async => const OutboundIpResult(
        url: 'https://www.cloudflare.com/cdn-cgi/trace',
        body: 'ip=203.0.113.7\nloc=HK\n',
        coreEpoch: 1,
        routeVersion: 1,
      ),
    );
  });

  Future<void> pump(WidgetTester tester, {bool started = true}) async {
    await tester.pumpWidget(
      TestApp(
        overrides: [
          runTimeProvider.overrideWithBuild((_, _) => started ? 1 : null),
          routeTrackerProvider.overrideWithBuild(
            (ref, _) => RouteState(
              coreEpoch: 1,
              routeVersion: 1,
              hostEpoch: 1,
              proxied: ref.watch(isStartProvider),
              synced: true,
              live: true,
            ),
          ),
          coreHandlerProvider.overrideWithValue(CoreController.scoped(core)),
        ],
        child: Scaffold(body: ListView(children: const [RouteCheckCard()])),
      ),
    );
    await tester.pumpAndSettle();
  }

  void answer(String label, ProbeResult? result) {
    final url = routeCheckTargets.firstWhere((t) => t.label == label).url;
    pending[url]!.complete(result);
  }

  test('the route check is a fork dashboard tile', () {
    expect(DashboardWidget.forkRouteCheck.card, isA<RouteCheckCard>());
  });

  testWidgets('checks nothing until asked, then routes every target', (
    tester,
  ) async {
    await pump(tester);
    expect(asked, isEmpty);
    expect(find.text('Not checked'), findsNWidgets(routeCheckTargets.length));
    expect(find.textContaining('203.0.113.7'), findsOneWidget);

    await tester.tap(find.byGlyph(AppGlyphs.bolt));
    await tester.pump();
    expect(asked.map((p) => p.url), routeCheckTargets.map((t) => t.url));
    expect(asked.map((p) => p.proxyName).toSet(), {''});
    expect(find.byType(CommonCircleLoading), findsWidgets);
    expect(find.text('Not checked'), findsNothing);
  });

  testWidgets('shows the delay, rule and chain, or why it failed', (
    tester,
  ) async {
    await pump(tester);
    await tester.tap(find.byGlyph(AppGlyphs.bolt));
    await tester.pump();

    answer('Google', _google);
    answer('GitHub', const ProbeResult(error: 'timeout', chains: ['Proxy']));
    answer('OKX', const ProbeResult(error: 'failed', message: 'refused'));
    answer('FCM', null);
    answer(
      'Baidu',
      const ProbeResult(
        statusCode: 200,
        delay: 12,
        chains: ['DIRECT'],
        rule: 'GeoSite',
        rulePayload: 'cn',
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('85 ms'), findsOneWidget);
    expect(
      find.text('DomainSuffix google.com · Proxy › HK 01'),
      findsOneWidget,
    );
    expect(find.text('Timeout'), findsOneWidget);
    expect(find.text('Check failed'), findsNWidgets(2));
    expect(find.text('12 ms'), findsOneWidget);
    expect(find.text('GeoSite cn · DIRECT'), findsOneWidget);
    expect(find.textContaining('HK 01'), findsNWidgets(2));
    expect(find.byType(CommonCircleLoading), findsNothing);
    expect(find.byGlyph(AppGlyphs.bolt), findsOneWidget);
  });

  testWidgets('a core error leaves the row failed and a rerun recovers', (
    tester,
  ) async {
    await pump(tester);
    await tester.tap(find.byGlyph(AppGlyphs.bolt));
    await tester.pump();
    for (final target in routeCheckTargets) {
      pending[target.url]!.completeError(StateError('core gone'));
    }
    await tester.pumpAndSettle();
    expect(find.text('Check failed'), findsNWidgets(routeCheckTargets.length));

    await tester.tap(find.byGlyph(AppGlyphs.bolt));
    await tester.pump();
    for (final target in routeCheckTargets) {
      answer(target.label, _google);
    }
    await tester.pumpAndSettle();
    expect(find.text('85 ms'), findsNWidgets(routeCheckTargets.length));
    expect(find.text('Check failed'), findsNothing);
  });

  testWidgets('stopped, every target goes out direct', (tester) async {
    await pump(tester, started: false);
    await tester.tap(find.byGlyph(AppGlyphs.bolt));
    await tester.pump();
    expect(asked.map((p) => p.proxyName).toSet(), {'DIRECT'});
  });
}
