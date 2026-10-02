import 'dart:async';

import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'package:fl_clash/providers/network_features.dart';
import 'package:fl_clash/providers/state.dart';
import 'package:fl_clash/views/service_checks.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Checker extends MediaUnlockChecker {
  int calls = 0;
  bool cancelled = false;
  Completer<Map<MediaPlatform, MediaUnlockResult>>? pending;

  @override
  Future<Map<MediaPlatform, MediaUnlockResult>> checkAll({
    List<MediaPlatform>? platforms,
    void Function(MediaUnlockResult result)? onProgress,
  }) async {
    calls++;
    const result = MediaUnlockResult(
      platform: MediaPlatform.netflix,
      status: MediaUnlockStatus.unlocked,
      region: 'US',
    );
    onProgress?.call(result);
    final pending = this.pending;
    if (pending != null) return pending.future;
    return {MediaPlatform.netflix: result};
  }

  @override
  void cancel() {
    cancelled = true;
    if (pending?.isCompleted == false) pending!.complete({});
    super.cancel();
  }
}

void main() {
  testWidgets('does not probe until requested and publishes results', (
    tester,
  ) async {
    final checker = _Checker();
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [selectedMapProvider.overrideWith((_) => const {})],
        homeBuilder: (child) => Scaffold(body: child),
        child: ServiceChecksView(checker: checker),
      ),
    );
    await tester.pumpAndSettle();
    expect(checker.calls, 0);
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(
      tester.element(find.byType(ServiceChecksView)),
    );
    expect(checker.calls, 1);
    expect(
      container
          .read(serviceCheckResultsProvider)[MediaPlatform.netflix]
          ?.region,
      'US',
    );
  });

  testWidgets('closing the view cancels pending checks', (tester) async {
    final checker = _Checker()..pending = Completer();
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [selectedMapProvider.overrideWith((_) => const {})],
        homeBuilder: (child) => Scaffold(body: child),
        child: ServiceChecksView(checker: checker),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pump();
    expect(checker.calls, 1);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(checker.cancelled, true);
    expect(tester.takeException(), isNull);
  });
}
