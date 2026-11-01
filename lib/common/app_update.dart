import 'dart:convert';

import 'package:dio/dio.dart';

const updateApkName = 'FlClash-alpha-arm64-v8a.apk';
const updateCertificate =
    '4cc5094e24f4a4cfde3a37d6c839ae376bd74c50075d8ee6bc73e25682e9afad';
const updateSources = [
  UpdateSource(
    name: 'GitHub',
    api:
        'https://github.com/initH271/FlClash-alpha/releases/latest/download/update.json',
    download: 'https://github.com/initH271/FlClash-alpha/releases/download',
  ),
  UpdateSource(
    name: 'CNB',
    api:
        'https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/update.json',
    download: 'https://cnb.cool/507space/FlClash-alpha/-/releases/download',
  ),
];

class UpdateSource {
  final String name;
  final String api;
  final String download;

  const UpdateSource({
    required this.name,
    required this.api,
    required this.download,
  });
}

typedef ReleaseLoader = Future<Map<String, dynamic>> Function(UpdateSource);
typedef DownloadProbe = Future<void> Function(String);

class AppUpdateChecker {
  final ReleaseLoader load;
  final DownloadProbe probe;
  final Duration timeout;

  AppUpdateChecker({
    required this.load,
    required this.probe,
    this.timeout = const Duration(seconds: 6),
  });

  factory AppUpdateChecker.network(Dio dio) => AppUpdateChecker(
    load: (source) async {
      final response = await dio.get<String>(
        source.api,
        options: Options(
          responseType: ResponseType.plain,
          sendTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 5),
        ),
      );
      final metadata = jsonDecode(response.data!) as Map<String, dynamic>;
      return {
        'tag_name': metadata['tag'],
        'body':
            '${metadata['notes'] ?? ''}\n<!-- flclash-update ${jsonEncode(metadata)} -->',
      };
    },
    probe: (url) async {
      await dio.head<void>(
        url,
        options: Options(
          sendTimeout: const Duration(seconds: 5),
          receiveTimeout: const Duration(seconds: 5),
        ),
      );
    },
  );

  /// Null when no channel offers a newer build; throws when no channel answered.
  Future<Map<String, dynamic>?> check(int installedBuild) async {
    final failures = <String>[];
    final releases = await Future.wait(
      updateSources.map((source) async {
        try {
          return (
            answered: true,
            release: await _candidate(source, installedBuild),
          );
        } catch (error) {
          failures.add('${source.name}: $error');
          return (answered: false, release: null);
        }
      }),
    );
    if (releases.every((item) => !item.answered)) {
      throw StateError('No update channel answered (${failures.join('; ')})');
    }
    final available =
        releases
            .map((item) => item.release)
            .whereType<Map<String, dynamic>>()
            .toList()
          ..sort((a, b) {
            final version = (b['build'] as int).compareTo(a['build'] as int);
            return version != 0
                ? version
                : (a['latency'] as int).compareTo(b['latency'] as int);
          });
    if (available.isEmpty) return null;
    final selected = available.first;
    return {
      ...selected,
      'download_urls': [
        for (final item in available)
          if (item['build'] == selected['build'] &&
              item['sha256'] == selected['sha256'])
            item['download_url'],
      ],
    };
  }

  Future<Map<String, dynamic>?> _candidate(
    UpdateSource source,
    int installedBuild,
  ) async {
    final watch = Stopwatch()..start();
    final release = await load(source).timeout(timeout);
    final Map<String, dynamic> metadata;
    final String body;
    final RegExpMatch marker;
    try {
      if (release['draft'] == true || release['prerelease'] == true) {
        return null;
      }
      body = release['body'] as String? ?? '';
      final found = RegExp(
        r'<!-- flclash-update (\{[^\r\n]*\}) -->',
      ).firstMatch(body);
      if (found == null) return null;
      marker = found;
      metadata = jsonDecode(marker.group(1)!) as Map<String, dynamic>;
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
    final build = metadata['build'];
    if (build is! int ||
        build <= installedBuild ||
        metadata['applicationId'] != 'com.follow.clash.dev' ||
        metadata['apk'] != updateApkName ||
        metadata['certificateSha256'] != updateCertificate ||
        metadata['sha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(metadata['sha256'] as String)) {
      return null;
    }
    final tag = release['tag_name'];
    if (tag is! String || tag.isEmpty) return null;
    final url = '${source.download}/${Uri.encodeComponent(tag)}/$updateApkName';
    await probe(url).timeout(timeout);
    return {
      'tag_name': tag,
      'body': body.replaceFirst(marker.group(0)!, '').trim(),
      'build': build,
      'source': source.name,
      'download_url': url,
      'latency': watch.elapsedMicroseconds,
      'sha256': metadata['sha256'],
      'displayVersion': metadata['displayVersion'],
      'upstreamVersion': metadata['upstreamVersion'] ?? metadata['version'],
      'revision': metadata['revision'],
      'publishedAt': metadata['publishedAt'] ?? release['published_at'],
    };
  }
}
