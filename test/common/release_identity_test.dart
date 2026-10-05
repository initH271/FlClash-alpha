import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/app_update.dart';
import 'package:fl_clash/common/release_identity.dart';
import 'package:flutter_test/flutter_test.dart';

class _DateAdapter implements HttpClientAdapter {
  final Map<String, dynamic> Function(RequestOptions) respond;

  _DateAdapter(this.respond);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async => ResponseBody.fromString(
    jsonEncode(respond(options)),
    200,
    headers: {
      Headers.contentTypeHeader: ['application/json'],
    },
  );

  @override
  void close({bool force = false}) {}
}

void main() {
  test(
    'legacy packages retain their tag and new packages use readable tags',
    () {
      final legacy = AppReleaseIdentity.installed('0.8.98', '2026094012');
      expect(legacy.displayVersion, '0.8.98-alpha.12');
      expect(legacy.releaseTag, 'alpha-0.8.98-2026094012');
      final current = AppReleaseIdentity.installed(
        '0.8.98-alpha.13',
        '2026094013',
      );
      expect(current.displayVersion, '0.8.98-alpha.13');
      expect(current.upstreamVersion, '0.8.98');
      expect(current.revision, 13);
      expect(current.build, 2026094013);
      expect(current.releaseTag, 'v0.8.98-alpha.13');
    },
  );

  test('unidentified development packages keep a truthful legacy label', () {
    final identity = AppReleaseIdentity.installed('0.8.97', '42');
    expect(identity.displayVersion, '0.8.97 (42)');
    expect(identity.revision, isNull);
    expect(identity.releaseTag, isNull);
  });

  test('update display accepts new metadata and legacy download tags', () {
    expect(
      releaseDisplayVersion({
        'displayVersion': '0.8.98-alpha.13',
        'tag_name': 'alpha-0.8.98-2026094013',
      }),
      '0.8.98-alpha.13',
    );
    expect(
      releaseDisplayVersion({'tag_name': 'alpha-0.8.98-2026094012'}),
      '0.8.98-alpha.12',
    );
    expect(releaseDisplayVersion({'tag_name': 'alpha-test'}), 'alpha-test');
  });

  test(
    'release date is read from the matching published release and cached',
    () async {
      var calls = 0;
      final dio = Dio()
        ..httpClientAdapter = _DateAdapter((options) {
          calls++;
          return {
            'tag_name': 'alpha-0.8.98-2026094013',
            'published_at': '2026-10-06T01:02:03Z',
            'draft': false,
            'prerelease': false,
          };
        });
      addTearDown(() => dio.close(force: true));
      final client = ReleaseDateClient(dio);
      final first = await client.lookup(
        'alpha-0.8.98-2026094013',
        CancelToken(),
      );
      expect(first, DateTime.utc(2026, 10, 6, 1, 2, 3));
      expect(
        await client.lookup('alpha-0.8.98-2026094013', CancelToken()),
        first,
      );
      expect(calls, 1);
    },
  );

  test('wrong release or unavailable primary date falls back to CNB', () async {
    final hosts = <String>[];
    final dio = Dio()
      ..httpClientAdapter = _DateAdapter((options) {
        hosts.add(options.uri.host);
        return {
          'tag_name': options.uri.host == 'api.github.com'
              ? 'alpha-0.8.98-2026094012'
              : 'alpha-0.8.98-2026094013',
          'published_at': '2026-10-06T01:02:03Z',
        };
      });
    addTearDown(() => dio.close(force: true));
    expect(
      await ReleaseDateClient(
        dio,
      ).lookup('alpha-0.8.98-2026094013', CancelToken()),
      DateTime.utc(2026, 10, 6, 1, 2, 3),
    );
    expect(hosts, ['api.github.com', 'api.cnb.cool']);
  });

  test('draft, malformed date and cancellation do not invent a date', () async {
    final dio = Dio()
      ..httpClientAdapter = _DateAdapter(
        (_) => {
          'tag_name': 'alpha-0.8.98-2026094013',
          'published_at': '2026094013',
          'draft': true,
        },
      );
    addTearDown(() => dio.close(force: true));
    final client = ReleaseDateClient(dio);
    expect(
      await client.lookup('alpha-0.8.98-2026094013', CancelToken()),
      isNull,
    );
    expect(await client.lookup('alpha-test', CancelToken()), isNull);
    expect(
      await client.lookup('alpha-0.8.98-2026094013', CancelToken()..cancel()),
      isNull,
    );
    expect(parseReleaseDate('2026094013'), isNull);
    expect(parseReleaseDate('2026-02-30T01:02:03Z'), isNull);
    expect(parseReleaseDate('2026-10-06T01:02:03'), isNull);
  });

  test(
    'update eligibility still compares internal builds across display versions',
    () async {
      final checker = AppUpdateChecker(
        load: (source) async {
          final metadata = {
            'build': source.name == 'GitHub' ? 2026094013 : 2026094012,
            'displayVersion': source.name == 'GitHub'
                ? '0.8.98-alpha.13'
                : '0.8.99-alpha.12',
            'upstreamVersion': source.name == 'GitHub' ? '0.8.98' : '0.8.99',
            'revision': source.name == 'GitHub' ? 13 : 12,
            'applicationId': 'com.follow.clash.dev',
            'apk': updateApkName,
            'certificateSha256': updateCertificate,
            'sha256': 'a' * 64,
          };
          return {
            'tag_name': 'alpha-0.8.98-${metadata['build']}',
            'body': '<!-- flclash-update ${jsonEncode(metadata)} -->',
          };
        },
        probe: (_) async {},
      );
      final selected = await checker.check(2026094012);
      expect(selected?['build'], 2026094013);
      expect(selected?['displayVersion'], '0.8.98-alpha.13');
      expect(selected?['upstreamVersion'], '0.8.98');
      expect(selected?['revision'], 13);
    },
  );
}
