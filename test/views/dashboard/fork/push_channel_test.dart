import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/dashboard/fork/push_channel.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/test_app.dart';

class _MockCore extends Mock implements CoreHandlerInterface {}

TrackerInfo _connection({
  required String host,
  required String port,
  required List<String> chains,
  String rule = 'DomainSuffix',
  String payload = 'google.com',
  String process = 'com.google.android.gms',
}) => TrackerInfo(
  id: '$host:$port',
  start: DateTime.utc(2026),
  metadata: Metadata(
    network: 'tcp',
    host: host,
    destinationIP: '142.250.1.188',
    destinationPort: port,
    process: process,
  ),
  chains: chains,
  rule: rule,
  rulePayload: payload,
);

final _web = _connection(
  host: 'www.google.com',
  port: '443',
  chains: const ['HK 01', 'Proxy'],
);

void main() {
  late _MockCore core;

  setUp(() => core = _MockCore());

  Future<void> pump(
    WidgetTester tester,
    List<TrackerInfo> connections, {
    Locale locale = const Locale('en'),
  }) async {
    when(() => core.getConnections()).thenAnswer((_) async => connections);
    await tester.pumpWidget(
      TestApp(
        locale: locale,
        overrides: [
          coreHandlerProvider.overrideWithValue(CoreController.scoped(core)),
          coreStatusProvider.overrideWithBuild((_, _) => CoreStatus.connected),
        ],
        child: Scaffold(body: ListView(children: const [PushChannelCard()])),
      ),
    );
    await tester.pump();
    await tester.pump();
  }

  Future<void> dispose(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 1));
  }

  test('the push channel is a fork dashboard tile', () {
    expect(DashboardWidget.forkPushChannel.card, isA<PushChannelCard>());
  });

  test('push connections are told apart by port or mtalk host', () {
    expect(isPushConnection(_web), isFalse);
    for (final host in ['mtalk.google.com', 'alt3-mtalk.google.com']) {
      expect(
        isPushConnection(
          _connection(host: host, port: '443', chains: const []),
        ),
        isTrue,
        reason: host,
      );
    }
  });

  testWidgets('a proxied 5228 connection shows its rule and chain', (
    tester,
  ) async {
    await pump(tester, [
      _web,
      _connection(
        host: 'mtalk.google.com',
        port: '5228',
        chains: const ['HK 01', 'Proxy'],
      ),
    ]);

    expect(find.text('Via proxy'), findsOneWidget);
    expect(find.text('mtalk.google.com:5228'), findsOneWidget);
    expect(
      find.text('DomainSuffix google.com · Proxy › HK 01'),
      findsOneWidget,
    );
    expect(find.text('www.google.com:443'), findsNothing);
    expect(find.text('No push connection'), findsNothing);
    await dispose(tester);
  });

  testWidgets('without a push connection it says so', (tester) async {
    await pump(tester, [_web], locale: const Locale('zh', 'CN'));

    expect(find.text('暂无推送连接'), findsOneWidget);
    expect(find.textContaining('mtalk.google.com:5228'), findsOneWidget);
    expect(find.text('经代理'), findsNothing);
    expect(find.text('未经代理'), findsNothing);
    await dispose(tester);
  });

  testWidgets('a push connection left DIRECT is flagged', (tester) async {
    await pump(tester, [
      _connection(
        host: 'mtalk.google.com',
        port: '5228',
        chains: const ['HK 01', 'Proxy'],
      ),
      _connection(
        host: 'alt1-mtalk.google.com',
        port: '5228',
        chains: const ['DIRECT'],
        rule: 'Match',
        payload: '',
      ),
    ]);

    expect(find.text('Not proxied'), findsOneWidget);
    expect(find.text('Via proxy'), findsNothing);
    expect(find.text('Match · DIRECT'), findsOneWidget);
    await dispose(tester);
  });
}
