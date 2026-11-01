import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:pointycastle/asn1.dart';
import 'package:pointycastle/export.dart'
    show
        PublicKeyParameter,
        RSAPublicKey,
        RSASignature,
        RSASigner,
        SHA256Digest;

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

const windowsApplicationId = '94491F5A-A742-4DFF-B144-119A92A2FFD1';
const updateInstallerName = 'FlClash-alpha-windows-amd64-setup.exe';
// /RELAUNCH is read by windows/packaging/exe/inno_setup.iss, and
// .automation/windows_smoke.ps1 installs with exactly this line.
const windowsInstallerArguments =
    '/SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH';
const windowsUpdateMaxBytes = 256 * 1024 * 1024;
// .automation/windows_release.py signs this prefix followed by the payload text.
const windowsManifestSignaturePrefix = 'FlClash-alpha-windows-update-v1\n';
// The public certificate of the APK signing key, whose SHA-256 is
// [updateCertificate]. .automation/windows_release.py reads it from this file.
const updateSigningCertificate =
    'MIIEGjCCAoKgAwIBAgIJAMJRDY7DsCgXMA0GCSqGSIb3DQEBCwUAMDoxCzAJBgNVBAYTAkNO'
    'MRAwDgYDVQQKEwdBbmRyb2lkMRkwFwYDVQQDExBQZXJzb25hbCBGbENsYXNoMCAXDTI2MDkx'
    'OTEwMzI1NVoYDzIwNTQwMjA0MTAzMjU1WjA6MQswCQYDVQQGEwJDTjEQMA4GA1UEChMHQW5k'
    'cm9pZDEZMBcGA1UEAxMQUGVyc29uYWwgRmxDbGFzaDCCAaIwDQYJKoZIhvcNAQEBBQADggGP'
    'ADCCAYoCggGBALzGLVlSOTUdvt/6Vx94a4lpfWWSj6cBDqEZT52eXUvrrXKwf3dX/gTZijGi'
    'qYpkHeNWy2rllUnH9yN5+qaNPKYXCyAKvgfvIZV0iFLhd3qR5qiu9YLghAk6At4sdOCoWj5a'
    'v6l4uT6VjTPb9RkJXbb2Ob7jT4kcBZSrr3Vb4Qv1vyzJPmWb0MZxmwvOAlV/NcuZeZXbSKiO'
    'raIyQBVeF1oyqiaUA0vdaI00Q7VKak0Gljcf5BoehMFluEEmrN+ScXv6EfiD5UrzkNlaSYKE'
    '80WHzAhaSRi4sGgaE14IRgcop3IBhjezK+3jUYWUtDr3HVJ9gGg6msXGXFktnWEzEqvuYNrt'
    'twkwUN7ePorbNvuKSw4ig7VY6aVZO4UuMMnuytr8btrk8I9AhJbSFHIoRVSoM3AYpKmj8o6A'
    'kmSj13JPB7S7xgLi6q04R+ozbrTii107MS73NtmMd01B6ZM5EArmW4v0xLYzypKM2Wkbjmui'
    'GBmQ53s1s3CR+Ec5KfDVdQIDAQABoyEwHzAdBgNVHQ4EFgQUkFu3zXEPP8Q2zpt0AWnl4i9L'
    'L5IwDQYJKoZIhvcNAQELBQADggGBAGwdIuF7YHkn37TI+UZaPEc/hzWoPlu0fgB5bwO26NOO'
    'hge91JUAJ7LSYw4N2Cd6DNnWc2A0EM2SVfAGF+/HeVmHkHYHIBg6tPpChPdW+KV3AvREtEY5'
    'AOeEE8/ZE3BWM2MtmUKmySdQER2mxFfnKPBNyWESe33Xlz5lioaFbM9+vL1KLREkLssfAluV'
    'Mjxrr4qF2dJHmf9Wr7F0zUcV3ASkCGz9hfRtlpCmxkvvyjg3A/wr0XZzvuKxyWRWCUcltiLe'
    'GT1UIczRhBR4yK0EYe8OLKE+0PoKuqgCjg//bnVMF0lYAyy79F/dCvytMfFJDVeRYbkAMG+A'
    '1rt3vbneUlbZdG/JitVgYvNas7pLxDsYki6Rzod7wvhcbZVR/TlwX9oEn8YJiExcm+mcrOts'
    'fjpxbXyZ4nL7imoG9KMAtZTIm/k02whNFW1nHXM8NNu1rbhXqKhHZkrjNlrdocJJQtdCL4T4'
    'NJMB0Hfe9QWiz/OCIwbk4r1wdAD9ZfoOhREsiw==';
const windowsUpdateSources = [
  UpdateSource(
    name: 'GitHub',
    api:
        'https://github.com/initH271/FlClash-alpha/releases/latest/download/update-windows.json',
    download: 'https://github.com/initH271/FlClash-alpha/releases/download',
  ),
  UpdateSource(
    name: 'CNB',
    api:
        'https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/update-windows.json',
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

class UpdateTarget {
  final String file;
  final List<UpdateSource> sources;
  final bool Function(Map<String, dynamic> metadata) accepts;

  const UpdateTarget({
    required this.file,
    required this.sources,
    required this.accepts,
  });
}

bool _isPersonalApk(Map<String, dynamic> metadata) =>
    metadata['applicationId'] == 'com.follow.clash.dev' &&
    metadata['apk'] == updateApkName &&
    metadata['certificateSha256'] == updateCertificate;

bool _isPersonalInstaller(Map<String, dynamic> metadata) {
  final size = metadata['size'];
  return metadata['applicationId'] == windowsApplicationId &&
      metadata['installer'] == updateInstallerName &&
      size is int &&
      size > 0 &&
      size <= windowsUpdateMaxBytes;
}

const androidUpdate = UpdateTarget(
  file: updateApkName,
  sources: updateSources,
  accepts: _isPersonalApk,
);
const windowsUpdate = UpdateTarget(
  file: updateInstallerName,
  sources: windowsUpdateSources,
  accepts: _isPersonalInstaller,
);

final RSAPublicKey _updateSigningKey = rsaKeyOfCertificate(
  updateSigningCertificate,
);

@visibleForTesting
RSAPublicKey rsaKeyOfCertificate(String certificate) {
  final parsed = ASN1Parser(base64.decode(certificate)).nextObject();
  final tbs = (parsed as ASN1Sequence).elements![0] as ASN1Sequence;
  // tbsCertificate: [0] version, serial, signature, issuer, validity, subject, key.
  final subjectKey = tbs.elements![6] as ASN1Sequence;
  final bits = (subjectKey.elements![1] as ASN1BitString).stringValues!;
  final key = ASN1Parser(Uint8List.fromList(bits)).nextObject() as ASN1Sequence;
  return RSAPublicKey(
    (key.elements![0] as ASN1Integer).integer!,
    (key.elements![1] as ASN1Integer).integer!,
  );
}

/// The signature covers the payload as sent, so nothing in it is parsed before
/// it is trusted. Throws on anything that does not verify.
Map<String, dynamic> readSignedManifest(String text, {RSAPublicKey? key}) {
  final envelope = jsonDecode(text) as Map<String, dynamic>;
  final payload = envelope['payload'] as String;
  final signature = base64.decode(envelope['signature'] as String);
  final verifier = RSASigner(SHA256Digest(), '0609608648016503040201')
    ..init(false, PublicKeyParameter<RSAPublicKey>(key ?? _updateSigningKey));
  final signed = utf8.encode('$windowsManifestSignaturePrefix$payload');
  if (!verifier.verifySignature(signed, RSASignature(signature))) {
    throw const FormatException('Update manifest signature mismatch');
  }
  return jsonDecode(utf8.decode(base64.decode(payload)))
      as Map<String, dynamic>;
}

typedef ReleaseLoader = Future<Map<String, dynamic>> Function(UpdateSource);
typedef DownloadProbe = Future<void> Function(String);

class AppUpdateChecker {
  final ReleaseLoader load;
  final DownloadProbe probe;
  final Duration timeout;
  final UpdateTarget target;

  AppUpdateChecker({
    required this.load,
    required this.probe,
    this.timeout = const Duration(seconds: 6),
    this.target = androidUpdate,
  });

  static Future<String> _fetch(Dio dio, UpdateSource source) async {
    final response = await dio.get<String>(
      source.api,
      options: Options(
        responseType: ResponseType.plain,
        sendTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 5),
      ),
    );
    return response.data!;
  }

  static Map<String, dynamic> _release(Map<String, dynamic> metadata) => {
    'tag_name': metadata['tag'],
    'body':
        '${metadata['notes'] ?? ''}\n<!-- flclash-update ${jsonEncode(metadata)} -->',
  };

  static DownloadProbe _head(Dio dio) => (url) async {
    await dio.head<void>(
      url,
      options: Options(
        sendTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 5),
      ),
    );
  };

  factory AppUpdateChecker.network(Dio dio) => AppUpdateChecker(
    load: (source) async =>
        _release(jsonDecode(await _fetch(dio, source)) as Map<String, dynamic>),
    probe: _head(dio),
  );

  /// The Windows files reach a Release after its APK and may never arrive for a
  /// failed build, so a missing manifest means no update rather than a failure.
  factory AppUpdateChecker.windows(Dio dio, {RSAPublicKey? key}) =>
      AppUpdateChecker(
        target: windowsUpdate,
        load: (source) async {
          final String text;
          try {
            text = await _fetch(dio, source);
          } on DioException catch (error) {
            if (error.response?.statusCode == 404) return const {};
            rethrow;
          }
          return _release(readSignedManifest(text, key: key));
        },
        probe: _head(dio),
      );

  /// Null when no channel offers a newer build; throws when no channel answered.
  Future<Map<String, dynamic>?> check(int installedBuild) async {
    final failures = <String>[];
    final releases = await Future.wait(
      target.sources.map((source) async {
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
    if (!target.accepts(metadata) ||
        build is! int ||
        build <= installedBuild ||
        metadata['sha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(metadata['sha256'] as String)) {
      return null;
    }
    final tag = release['tag_name'];
    if (tag is! String || tag.isEmpty) return null;
    final url = '${source.download}/${Uri.encodeComponent(tag)}/${target.file}';
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
