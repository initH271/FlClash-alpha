import 'dart:async';

import 'package:fl_clash/common/update_check_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('startup, foreground interval and same-build deduplication', (
    tester,
  ) async {
    var calls = 0;
    var build = 20;
    final notified = <int>[];
    final scheduler = UpdateCheckScheduler(
      load: () async {
        calls++;
        return {'build': build};
      },
      notify: (release) async => notified.add(release['build'] as int),
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      await scheduler.check();
      expect(calls, 0);
      scheduler.setEnabled(true);
      await tester.pump();
      expect(calls, 1);
      expect(notified, [20]);
      await scheduler.check();
      await tester.pump(const Duration(minutes: 59));
      expect(calls, 1);
      await tester.pump(const Duration(minutes: 1));
      expect(calls, 2);
      expect(notified, [20]);
      build = 21;
      await tester.pump(const Duration(hours: 1));
      expect(calls, 3);
      expect(notified, [20, 21]);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('background pauses timers and foreground catches up once', (
    tester,
  ) async {
    var calls = 0;
    final scheduler = UpdateCheckScheduler(
      load: () async {
        calls++;
        return null;
      },
      notify: (_) async => fail('no release'),
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      scheduler.setEnabled(true);
      await tester.pump();
      scheduler.setForeground(false);
      await tester.pump(const Duration(hours: 12));
      expect(calls, 1);
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 2);
      scheduler.setForeground(false);
      await tester.pump(const Duration(minutes: 1));
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 2);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('a result arriving in the background is deferred until resume', (
    tester,
  ) async {
    final result = Completer<Map<String, dynamic>?>();
    var calls = 0;
    var notifications = 0;
    final scheduler = UpdateCheckScheduler(
      load: () {
        calls++;
        return result.future;
      },
      notify: (_) async => notifications++,
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      scheduler.setEnabled(true);
      scheduler.setForeground(false);
      result.complete({'build': 20});
      await tester.pump();
      expect(notifications, 0);
      scheduler.setForeground(true);
      await tester.pump();
      expect(notifications, 1);
      expect(calls, 1);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('overlapping triggers share a check and a single dialog', (
    tester,
  ) async {
    final result = Completer<Map<String, dynamic>?>();
    final dialog = Completer<void>();
    var calls = 0;
    var notifications = 0;
    final scheduler = UpdateCheckScheduler(
      load: () {
        calls++;
        return result.future;
      },
      notify: (_) {
        notifications++;
        return dialog.future;
      },
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      scheduler.setEnabled(true);
      final first = scheduler.check();
      expect(scheduler.check(), same(first));
      expect(calls, 1);
      result.complete({'build': 20});
      await tester.pump();
      await tester.pump(const Duration(hours: 12));
      expect(notifications, 1);
      expect(scheduler.check(), same(first));
      scheduler.setEnabled(false);
      dialog.complete();
      await first;
      expect(notifications, 1);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('disabling drops late results and re-enabling checks afresh', (
    tester,
  ) async {
    final result = Completer<Map<String, dynamic>?>();
    var calls = 0;
    var notifications = 0;
    final scheduler = UpdateCheckScheduler(
      load: () {
        calls++;
        return calls == 1 ? result.future : Future.value({'build': 21});
      },
      notify: (_) async => notifications++,
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      scheduler.setEnabled(true);
      scheduler.setEnabled(false);
      scheduler.setEnabled(true);
      result.complete({'build': 20});
      await tester.pump();
      await tester.pump();
      expect(calls, 2);
      expect(notifications, 1);
      scheduler.setEnabled(false);
      await tester.pump(const Duration(days: 1));
      expect(calls, 2);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets(
    'synchronous failures release the guard and retry after the delay',
    (tester) async {
      var calls = 0;
      final errors = <Object>[];
      final scheduler = UpdateCheckScheduler(
        load: () {
          calls++;
          if (calls == 1) throw StateError('offline');
          return Future.value(null);
        },
        notify: (_) async => fail('no release'),
        now: tester.binding.clock.now,
        onError: errors.add,
      );
      try {
        scheduler.setEnabled(true);
        await tester.pump();
        expect(errors, hasLength(1));
        await tester.pump(const Duration(minutes: 5));
        expect(calls, 2);
      } finally {
        scheduler.dispose();
      }
    },
  );

  testWidgets('disposal ignores late results and never arms another timer', (
    tester,
  ) async {
    final result = Completer<Map<String, dynamic>?>();
    var notifications = 0;
    final scheduler = UpdateCheckScheduler(
      load: () => result.future,
      notify: (_) async => notifications++,
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    scheduler.setEnabled(true);
    scheduler.dispose();
    result.complete({'build': 20});
    await tester.pump();
    await tester.pump(const Duration(days: 1));
    expect(notifications, 0);
    expect(await scheduler.check(), isFalse);
  });

  testWidgets('traces why a check ran, found nothing or was skipped', (
    tester,
  ) async {
    final traces = <String>[];
    Map<String, dynamic>? release;
    final scheduler = UpdateCheckScheduler(
      load: () async => release,
      notify: (_) async {},
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
      trace: traces.add,
    );
    try {
      await scheduler.check();
      expect(traces, ['skipped: enabled=false foreground=true']);
      traces.clear();
      scheduler.setEnabled(true);
      await tester.pump();
      expect(traces, ['started', 'no newer build']);
      traces.clear();
      await scheduler.check();
      expect(traces.single, startsWith('skipped: last check at'));
      traces.clear();
      release = {'build': 21, 'tag_name': 'v21'};
      await tester.pump(const Duration(hours: 1));
      expect(traces, ['started', 'found v21']);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('resume within the hour is skipped, after an hour checks', (
    tester,
  ) async {
    var calls = 0;
    final scheduler = UpdateCheckScheduler(
      load: () async {
        calls++;
        return null;
      },
      notify: (_) async => fail('no release'),
      now: tester.binding.clock.now,
      onError: (_) => fail('unexpected error'),
    );
    try {
      scheduler.setEnabled(true);
      await tester.pump();
      expect(calls, 1);
      scheduler.setForeground(false);
      await tester.pump(const Duration(minutes: 59));
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 1);
      scheduler.setForeground(false);
      await tester.pump(const Duration(minutes: 2));
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 2);
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('a failed check does not count: the next resume retries', (
    tester,
  ) async {
    var calls = 0;
    final errors = <Object>[];
    final scheduler = UpdateCheckScheduler(
      load: () async {
        calls++;
        if (calls == 1) throw StateError('offline');
        return null;
      },
      notify: (_) async => fail('no release'),
      now: tester.binding.clock.now,
      onError: errors.add,
    );
    try {
      scheduler.setEnabled(true);
      await tester.pump();
      expect(calls, 1);
      expect(errors, hasLength(1));
      scheduler.setForeground(false);
      await tester.pump(const Duration(minutes: 1));
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 2);
      expect(errors, hasLength(1));
      scheduler.setForeground(false);
      await tester.pump(const Duration(minutes: 1));
      scheduler.setForeground(true);
      await tester.pump();
      expect(calls, 2, reason: 'the success counts as checked');
    } finally {
      scheduler.dispose();
    }
  });

  testWidgets('failures while foregrounded retry after the delay, no spin', (
    tester,
  ) async {
    var calls = 0;
    final errors = <Object>[];
    final scheduler = UpdateCheckScheduler(
      load: () async {
        calls++;
        if (calls <= 2) throw StateError('offline');
        return null;
      },
      notify: (_) async => fail('no release'),
      now: tester.binding.clock.now,
      onError: errors.add,
      retryDelay: const Duration(minutes: 5),
    );
    try {
      scheduler.setEnabled(true);
      await tester.pump();
      await tester.pump();
      expect(calls, 1);
      await tester.pump(const Duration(minutes: 4, seconds: 59));
      expect(calls, 1);
      await tester.pump(const Duration(seconds: 1));
      expect(calls, 2);
      await tester.pump(const Duration(minutes: 4, seconds: 59));
      expect(calls, 2);
      await tester.pump(const Duration(seconds: 1));
      expect(calls, 3);
      expect(errors, hasLength(2));
      await tester.pump(const Duration(minutes: 59));
      expect(calls, 3, reason: 'success returns to the regular interval');
      await tester.pump(const Duration(minutes: 1));
      expect(calls, 4);
    } finally {
      scheduler.dispose();
    }
  });
}
