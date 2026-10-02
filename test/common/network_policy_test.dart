import 'dart:async';

import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/models/network_features.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'QUIC rejection precedes subscription rules without mutating source',
    () {
      final source = <String, dynamic>{
        'rules': ['DOMAIN,example.com,DIRECT', 'MATCH,Proxy'],
      };
      final result = applyNetworkFeatures(
        source,
        const NetworkFeatureSettings(disableQuic: true),
      );
      expect(result['rules'], [
        quicRejectRule,
        'DOMAIN,example.com,DIRECT',
        'MATCH,Proxy',
      ]);
      expect(source['rules'], ['DOMAIN,example.com,DIRECT', 'MATCH,Proxy']);
      expect(
        applyNetworkFeatures(
          result,
          const NetworkFeatureSettings(disableQuic: true),
        )['rules'],
        result['rules'],
      );
      expect(
        applyNetworkFeatures(source, const NetworkFeatureSettings()),
        source,
      );
    },
  );

  test('disabled overrides preserve subscription configuration', () {
    final source = <String, dynamic>{
      'sniffer': {
        'enable': false,
        'skip-domain': ['private.example'],
      },
      'ntp': {'enable': false, 'server': 'time.example'},
    };
    expect(
      applyNetworkFeatures(source, const NetworkFeatureSettings()),
      source,
    );
    final result = applyNetworkFeatures(
      source,
      const NetworkFeatureSettings(overrideSniffer: true, overrideNtp: true),
    );
    expect(result['sniffer']['enable'], true);
    expect(result['sniffer']['skip-domain'], ['private.example']);
    expect(result['ntp']['write-to-system'], false);
    expect(source['ntp']['enable'], false);
  });

  test('matches IPv4/CIDR and gateway rules independently', () {
    const snapshot = NetworkSnapshot(
      addresses: ['192.168.10.22'],
      gateways: ['192.168.10.1'],
    );
    expect(NetworkRules.matches(snapshot, '192.168.10.0/24'), true);
    expect(NetworkRules.matches(snapshot, 'gateway:192.168.10.1'), true);
    expect(NetworkRules.matches(snapshot, '192.168.10.1'), false);
    expect(
      NetworkRules.matches(snapshot, '10.0.0.0/8\ngateway:192.168.10.1'),
      true,
    );
    for (final rule in [
      '256.1.1.1',
      '192.168.1.0/33',
      'gateway:invalid',
      '1.2.3.4/-1',
    ]) {
      expect(NetworkRules.isValid(rule), false, reason: rule);
    }
    expect(NetworkRules.isValid(''), true);
  });

  test('resumes only a session previously stopped by automation', () async {
    final policy = AutomaticStopPolicy();
    final calls = <bool>[];
    Future<bool> apply(bool running) async {
      calls.add(running);
      return true;
    }

    await policy.reconcile(
      enabled: true,
      matches: false,
      running: false,
      apply: apply,
    );
    expect(calls, isEmpty);
    await policy.reconcile(
      enabled: true,
      matches: true,
      running: true,
      apply: apply,
    );
    await policy.reconcile(
      enabled: true,
      matches: true,
      running: false,
      apply: apply,
    );
    await policy.reconcile(
      enabled: true,
      matches: false,
      running: false,
      apply: apply,
    );
    expect(calls, [false, true]);
  });

  test(
    'manual intent while automatic stop is pending prevents later resume',
    () async {
      final policy = AutomaticStopPolicy();
      final completion = Completer<bool>();
      final calls = <bool>[];
      final stopping = policy.reconcile(
        enabled: true,
        matches: true,
        running: true,
        apply: (running) {
          calls.add(running);
          return completion.future;
        },
      );
      policy.userIntent();
      completion.complete(true);
      await stopping;
      await policy.reconcile(
        enabled: true,
        matches: false,
        running: false,
        apply: (running) async {
          calls.add(running);
          return true;
        },
      );
      expect(calls, [false]);
      expect(policy.pausedByPolicy, false);
    },
  );

  test('stop failure does not claim an automatically paused session', () async {
    final policy = AutomaticStopPolicy();
    await expectLater(
      policy.reconcile(
        enabled: true,
        matches: true,
        running: true,
        apply: (_) async => throw StateError('failed'),
      ),
      throwsStateError,
    );
    expect(policy.pausedByPolicy, false);
  });
}
