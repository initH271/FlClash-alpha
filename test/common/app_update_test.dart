import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/app_update.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/update_sources.dart';

Map<String, dynamic> release(int build) {
  final metadata = {
    'build': build,
    'applicationId': 'com.follow.clash.dev',
    'apk': updateApkName,
    'certificateSha256': updateCertificate,
    'sha256':
        '0000000000000000000000000000000000000000000000000000000000000000',
  };
  return {
    'tag_name': 'alpha-$build',
    'body': 'Changes\n<!-- flclash-update ${jsonEncode(metadata)} -->',
  };
}

void main() {
  final twoSources = mirrored(androidUpdate);

  test(
    'the public update manifest and APK endpoint work without credentials',
    () async {
      final dio = Dio(BaseOptions(connectTimeout: const Duration(seconds: 5)));
      try {
        for (final source in updateSources) {
          final response = await dio.get<String>(
            source.api,
            options: Options(responseType: ResponseType.plain),
          );
          final metadata = jsonDecode(response.data!) as Map<String, dynamic>;
          expect(metadata['applicationId'], 'com.follow.clash.dev');
          final url = '${source.download}/${metadata['tag']}/$updateApkName';
          expect((await dio.head<void>(url)).statusCode, 200);
        }
        final result = await AppUpdateChecker.network(dio).check(0);
        expect(result, isNotNull);
        expect(result?['source'], 'GitHub');
      } finally {
        dio.close(force: true);
      }
    },
    skip: !const bool.fromEnvironment('RUN_UPDATE_NETWORK_TESTS'),
  );

  test('the app asks GitHub alone and downloads from its release', () async {
    const releases = 'https://github.com/initH271/FlClash-alpha/releases';
    final asked = <String>[];
    final checker = AppUpdateChecker(
      load: (source) async {
        asked.add(source.api);
        return release(20);
      },
      probe: (_) async {},
    );
    final result = await checker.check(19);
    expect(asked, ['$releases/latest/download/update.json']);
    expect(result?['source'], 'GitHub');
    expect(result?['download_urls'], [
      '$releases/download/alpha-20/$updateApkName',
    ]);
    expect(windowsUpdateSources.map((source) => source.api), [
      '$releases/latest/download/update-windows.json',
    ]);
    expect(windowsUpdateSources.map((source) => source.download), [
      '$releases/download',
    ]);
  });

  test('selects faster reachable mirror of the same version', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async {
        if (source == primarySource) {
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        return release(20);
      },
      probe: (_) async {},
    );
    final result = await checker.check(19);
    expect(result?['source'], mirrorSource.name);
    expect(result?['body'], 'Changes');
    expect(result?['download_url'], contains('/alpha-20/$updateApkName'));
  });

  test('newest version wins over a faster stale mirror', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async => release(source == primarySource ? 21 : 20),
      probe: (_) async {},
    );
    expect((await checker.check(19))?['build'], 21);
  });

  test('failed metadata endpoint falls back to the other mirror', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async {
        if (source == mirrorSource) throw StateError('unreachable');
        return release(20);
      },
      probe: (_) async {},
    );
    expect((await checker.check(19))?['source'], primarySource.name);
  });

  test('unavailable APK is not selected', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (_) async => release(20),
      probe: (url) async {
        if (url.startsWith(mirrorSource.download)) {
          throw StateError('missing APK');
        }
      },
    );
    expect((await checker.check(19))?['source'], primarySource.name);
  });

  test('a hung mirror cannot block checks indefinitely', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      timeout: const Duration(milliseconds: 20),
      load: (source) => source == primarySource
          ? Completer<Map<String, dynamic>>().future
          : Future.value(release(20)),
      probe: (_) async {},
    );
    expect((await checker.check(19))?['source'], mirrorSource.name);
  });

  test('same and older builds never prompt or download', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async => release(source == primarySource ? 20 : 19),
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(20), isNull);
  });

  test('foreign releases and malformed metadata are rejected', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async => source == primarySource
          ? {'tag_name': 'v99', 'body': 'Upstream release'}
          : {'tag_name': 'v99', 'body': '<!-- flclash-update {bad} -->'},
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(1), isNull);
  });

  test('every channel failing throws instead of reporting no update', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (_) async => throw StateError('offline'),
      probe: (_) async {},
    );
    await expectLater(checker.check(19), throwsStateError);
  });

  test('every channel timing out throws', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      timeout: const Duration(milliseconds: 20),
      load: (_) => Completer<Map<String, dynamic>>().future,
      probe: (_) async {},
    );
    await expectLater(checker.check(19), throwsStateError);
  });

  test('every APK probe failing throws', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (_) async => release(20),
      probe: (_) async => throw StateError('missing APK'),
    );
    await expectLater(checker.check(19), throwsStateError);
  });

  test('one channel answering no update beats a failing channel', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async {
        if (source == mirrorSource) throw StateError('unreachable');
        return release(19);
      },
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(19), isNull);
  });

  test('rejected releases count as answers, not failures', () async {
    final checker = AppUpdateChecker(
      target: twoSources,
      load: (source) async => source == primarySource
          ? {'tag_name': 'v99', 'body': 'no marker'}
          : {'tag_name': 'v99', 'body': '<!-- flclash-update {bad} -->'},
      probe: (_) async => fail('No probe expected'),
    );
    expect(await checker.check(1), isNull);
  });
}
