import 'dart:async';
import 'dart:convert';

import 'package:fl_clash/common/app_update.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> release(int build) => {
  'tag_name': 'alpha-$build',
  'body':
      'Changes\n<!-- flclash-update ${jsonEncode({'build': build, 'applicationId': 'com.follow.clash.dev', 'apk': updateApkName})} -->',
};

void main() {
  test('selects faster reachable mirror of the same version', () async {
    final checker = AppUpdateChecker(
      load: (source) async {
        if (source.name == 'GitHub') {
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        return release(20);
      },
      probe: (_) async {},
    );
    final result = await checker.check(19);
    expect(result?['source'], 'CNB');
    expect(result?['body'], 'Changes');
    expect(result?['download_url'], contains('/alpha-20/$updateApkName'));
  });

  test('newest version wins over a faster stale mirror', () async {
    final checker = AppUpdateChecker(
      load: (source) async => release(source.name == 'GitHub' ? 21 : 20),
      probe: (_) async {},
    );
    expect((await checker.check(19))?['build'], 21);
  });

  test('failed metadata endpoint falls back to the other mirror', () async {
    final checker = AppUpdateChecker(
      load: (source) async {
        if (source.name == 'CNB') throw StateError('unreachable');
        return release(20);
      },
      probe: (_) async {},
    );
    expect((await checker.check(19))?['source'], 'GitHub');
  });

  test('unavailable APK is not selected', () async {
    final checker = AppUpdateChecker(
      load: (_) async => release(20),
      probe: (url) async {
        if (url.contains('api.cnb.cool')) throw StateError('missing APK');
      },
    );
    expect((await checker.check(19))?['source'], 'GitHub');
  });

  test('a hung mirror cannot block checks indefinitely', () async {
    final checker = AppUpdateChecker(
      timeout: const Duration(milliseconds: 20),
      load: (source) => source.name == 'GitHub'
          ? Completer<Map<String, dynamic>>().future
          : Future.value(release(20)),
      probe: (_) async {},
    );
    expect((await checker.check(19))?['source'], 'CNB');
  });

  test('same and older builds never prompt or download', () async {
    final checker = AppUpdateChecker(
      load: (source) async => release(source.name == 'GitHub' ? 20 : 19),
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(20), isNull);
  });

  test('foreign releases and malformed metadata are rejected', () async {
    final checker = AppUpdateChecker(
      load: (source) async => source.name == 'GitHub'
          ? {'tag_name': 'v99', 'body': 'Upstream release'}
          : {'tag_name': 'v99', 'body': '<!-- flclash-update {bad} -->'},
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(1), isNull);
  });
}
