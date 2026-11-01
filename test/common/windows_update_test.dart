import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:fl_clash/common/app_update.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:pointycastle/export.dart';

// Made once by .automation/windows_release.py (keytool and openssl) with a key
// that was then thrown away, so the Python signer and the Dart verifier have to
// agree byte for byte.
const _opensslCertificate =
    'MIIC6jCCAdKgAwIBAgIJAKl1INbMp+CiMA0GCSqGSIb3DQEBCwUAMCIxIDAeBgNVBAMTF0'
    'ZsQ2xhc2gtYWxwaGEgdGVzdCBvbmx5MCAXDTI2MTEwMTA4MzQ1OVoYDzIxMjYxMDA4MDgz'
    'NDU5WjAiMSAwHgYDVQQDExdGbENsYXNoLWFscGhhIHRlc3Qgb25seTCCASIwDQYJKoZIhv'
    'cNAQEBBQADggEPADCCAQoCggEBAJ3JLdFF/V4Aq8+lCkoyMqS789I2A8YWu6JVPa0tu1mW'
    'B0gRjpgAy/FBG8Sf06QMiQv5LwndJ/wKeOoigWV8W3aO2RaPhlHiy3CBkjoiGZYpOEtf4R'
    'lfFWG7zI7aJP9nQ8iPIc2bHxT4K+eV+tXQYo9/Tkq2Lg6GDfTW+aQvvikoRmYUpP5yvYpa'
    '5a7fcV7UJhGKn3/tHBVQMxN1vBhYKjq7E0ndyAWVN+bdefCq9K8MTsCIw0prHyM4vaSmht'
    '67uKFrQwjpz4UiLsfWgIjb564YwbmQAJJbchLFnrka9igK2pgZ8id98fbghBftfVv7i17y'
    'b9sj5ySSbDVnbSQYWQECAwEAAaMhMB8wHQYDVR0OBBYEFNSSfMjgaGhort+2fJpu6nPT9R'
    '7MMA0GCSqGSIb3DQEBCwUAA4IBAQA+UbESVHzH/nDl6aRUqf+7wU3GYLIW3/ETOE2e6Wgs'
    'WGuB1imwuqBWo2Y4lw2+slrPGnYurwODQMAb5hkbh4MKETEFMd26NtthrgGh8N7DVnsclk'
    'Mrl6oEvJUxqS0EJCSyl96bPhgPBTXiOEFOV4HVQvIIVnxqnkDS/KXOV4oBXeR70neSr61S'
    'V912LuaQFPdzQI39qRHgZR81GQkx7ccGPDiieCB41bxP7D+8oinAC0zzeK9nrQhpfrAN2Z'
    'hYSKzOQcHGfK80sDvuNb/X5bHqpyzkalNlA7cfRnWQUgeQICfWK/uyjpm6KF18q7ZYnQ3O'
    'cVO2gEMjfZ9zq8z8bWGA';
const _opensslPayload =
    'eyJ0YWciOiJ2MC45LjItYWxwaGEuMjIiLCJidWlsZCI6MjAyNjA5NDAyMiwiZGlzcGxheV'
    'ZlcnNpb24iOiIwLjkuMi1hbHBoYS4yMiIsIm5vdGVzIjoi6K+05piOIiwiYXBwbGljYXRp'
    'b25JZCI6Ijk0NDkxRjVBLUE3NDItNERGRi1CMTQ0LTExOUE5MkEyRkZEMSIsImluc3RhbG'
    'xlciI6IkZsQ2xhc2gtYWxwaGEtd2luZG93cy1hbWQ2NC1zZXR1cC5leGUiLCJzaGEyNTYi'
    'OiJhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYW'
    'FhYWFhYWFhYWFhYWFhIiwic2l6ZSI6NDM1MjgzMDEsInB1Ymxpc2hlZEF0IjoiMjAyNi0x'
    'MS0wMlQxMDowMDowMFoifQ==';
const _opensslSignature =
    'Zulzi5Sr+f1MxdZHRRXXi4ZMB/saL/rzf6izf9YfyBKqn6o409Qh+N88h3rLcqJMzvs/G9'
    'cmY8tc1LECqnlGOGko2np9ryQRZQro4ICEXFORC4fXHPsW5WtONh0y6iFZqpeWWuP09a+q'
    'UIqAAWUvfQLeyGx5ftKClGzoMoOUlfsTc9gAprAHC2QYwVqGIFOLkm4BPhtUjLo/0k5Zdz'
    '1nkVbabGNnCDb8MOM1B885UaBxWNaz22ozqJfIENEFGZ7v12EX4g/JI1l27LWY+lxs8GPg'
    '8n7Uj617fe69hL3BlJYUbDcI7udqaMLvmHPDYZC8xKqWbOEduzM5EoQr5rZ/Dg==';

final _setupHash = sha256.convert(utf8.encode('setup')).toString();

Map<String, dynamic> _payload({
  int build = 2026094022,
  String applicationId = windowsApplicationId,
  String installer = updateInstallerName,
  Object size = 5,
}) => {
  'tag': 'v0.9.2-alpha.22',
  'build': build,
  'displayVersion': '0.9.2-alpha.22',
  'notes': 'Changes',
  'applicationId': applicationId,
  'installer': installer,
  'sha256': _setupHash,
  'size': size,
};

Uint8List _sign(RSAPrivateKey key, List<int> bytes) {
  final signer = RSASigner(SHA256Digest(), '0609608648016503040201')
    ..init(true, PrivateKeyParameter<RSAPrivateKey>(key));
  return signer.generateSignature(Uint8List.fromList(bytes)).bytes;
}

String _manifest(
  RSAPrivateKey key,
  Map<String, dynamic> payload, {
  String prefix = windowsManifestSignaturePrefix,
}) {
  final encoded = base64.encode(utf8.encode(jsonEncode(payload)));
  return jsonEncode({
    'payload': encoded,
    'signature': base64.encode(_sign(key, utf8.encode('$prefix$encoded'))),
  });
}

class _Adapter implements HttpClientAdapter {
  final Map<String, ({int status, String body})> answers;
  final requested = <String>[];

  _Adapter(this.answers);

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final url = options.uri.toString();
    requested.add('${options.method} $url');
    if (options.method == 'HEAD') {
      return ResponseBody.fromString('', 200);
    }
    final answer = answers[Uri.parse(url).host];
    if (answer == null) throw StateError('offline');
    return ResponseBody.fromString(answer.body, answer.status);
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  late RSAPublicKey publicKey;
  late RSAPrivateKey privateKey;

  setUpAll(() {
    final random = FortunaRandom()
      ..seed(
        KeyParameter(
          Uint8List.fromList(List.generate(32, (_) => Random().nextInt(256))),
        ),
      );
    final generator = RSAKeyGenerator()
      ..init(
        ParametersWithRandom(
          RSAKeyGeneratorParameters(BigInt.from(65537), 2048, 64),
          random,
        ),
      );
    final pair = generator.generateKeyPair();
    publicKey = pair.publicKey;
    privateKey = pair.privateKey;
  });

  group('signed manifest', () {
    test('the app carries the certificate that signs the APK', () {
      final der = base64.decode(updateSigningCertificate);
      expect(sha256.convert(der).toString(), updateCertificate);
      final key = rsaKeyOfCertificate(updateSigningCertificate);
      expect(key.modulus!.bitLength, 3072);
      expect(key.publicExponent, BigInt.from(65537));
    });

    test('accepts what the release script signs', () {
      final manifest = readSignedManifest(
        jsonEncode({
          'payload': _opensslPayload,
          'signature': _opensslSignature,
        }),
        key: rsaKeyOfCertificate(_opensslCertificate),
      );
      expect(manifest['tag'], 'v0.9.2-alpha.22');
      expect(manifest['notes'], '说明');
      expect(manifest['applicationId'], windowsApplicationId);
    });

    test('refuses it under the certificate of the real key', () {
      expect(
        () => readSignedManifest(
          jsonEncode({
            'payload': _opensslPayload,
            'signature': _opensslSignature,
          }),
        ),
        throwsFormatException,
      );
    });

    test('refuses a changed payload', () {
      final envelope =
          jsonDecode(_manifest(privateKey, _payload())) as Map<String, dynamic>;
      envelope['payload'] = base64.encode(
        utf8.encode(jsonEncode(_payload(build: 9999999999))),
      );
      expect(
        () => readSignedManifest(jsonEncode(envelope), key: publicKey),
        throwsFormatException,
      );
    });

    test('refuses a signature made without the domain prefix', () {
      expect(
        () => readSignedManifest(
          _manifest(privateKey, _payload(), prefix: ''),
          key: publicKey,
        ),
        throwsFormatException,
      );
    });

    test('refuses a signature of the wrong length or none', () {
      final envelope =
          jsonDecode(_manifest(privateKey, _payload())) as Map<String, dynamic>;
      for (final signature in ['AAAA', '', null]) {
        expect(
          () => readSignedManifest(
            jsonEncode({...envelope, 'signature': signature}),
            key: publicKey,
          ),
          throwsA(anything),
        );
      }
    });
  });

  group('Windows update check', () {
    const github = 'github.com';
    const cnb = 'cnb.cool';

    ({int status, String body}) signed(Map<String, dynamic> payload) =>
        (status: 200, body: _manifest(privateKey, payload));
    const missing = (status: 404, body: 'Not Found');

    Future<Map<String, dynamic>?> check(
      _Adapter adapter, {
      int installed = 2026094021,
    }) {
      final dio = Dio()..httpClientAdapter = adapter;
      return AppUpdateChecker.windows(dio, key: publicKey).check(installed);
    }

    test('offers a signed newer build from both sources', () async {
      final adapter = _Adapter({
        github: signed(_payload()),
        cnb: signed(_payload()),
      });
      final result = await check(adapter);
      expect(result?['build'], 2026094022);
      expect(result?['sha256'], _setupHash);
      expect(result?['body'], 'Changes');
      expect(result?['download_urls'], hasLength(2));
      expect(
        result?['download_url'],
        endsWith('/v0.9.2-alpha.22/$updateInstallerName'),
      );
      expect(
        adapter.requested.where((url) => url.startsWith('GET')).toSet(),
        windowsUpdateSources.map((source) => 'GET ${source.api}').toSet(),
      );
    });

    test(
      'a release without Windows files is no update, not an error',
      () async {
        final adapter = _Adapter({github: missing, cnb: missing});
        expect(await check(adapter), isNull);
      },
    );

    test('a missing manifest on one source leaves the other', () async {
      final adapter = _Adapter({github: missing, cnb: signed(_payload())});
      expect((await check(adapter))?['source'], 'CNB');
    });

    test('a broken source leaves the other', () async {
      final tampered = jsonDecode(_manifest(privateKey, _payload()));
      tampered['payload'] = base64.encode(utf8.encode('{"build":9999999999}'));
      for (final broken in [
        (status: 200, body: jsonEncode(tampered)),
        (status: 200, body: '<html>mirror error</html>'),
        (status: 500, body: 'oops'),
      ]) {
        final adapter = _Adapter({github: broken, cnb: signed(_payload())});
        final result = await check(adapter);
        expect(result?['source'], 'CNB');
        expect(result?['download_urls'], hasLength(1));
      }
    });

    test('an unreachable source leaves the other', () async {
      final adapter = _Adapter({cnb: signed(_payload())});
      expect((await check(adapter))?['source'], 'CNB');
    });

    test('every source failing its signature is an error', () async {
      final foreign = (status: 200, body: _manifest(privateKey, _payload()));
      final dio = Dio()
        ..httpClientAdapter = _Adapter({github: foreign, cnb: foreign});
      await expectLater(
        AppUpdateChecker.windows(dio).check(2026094021),
        throwsStateError,
      );
    });

    test('a signed manifest for something else is not offered', () async {
      for (final payload in [
        _payload(applicationId: '728B3532-C74B-4870-9068-BE70FE12A3E6'),
        _payload(applicationId: 'com.follow.clash.dev'),
        _payload(installer: updateApkName),
        _payload(size: 0),
        _payload(size: windowsUpdateMaxBytes + 1),
        _payload(size: 'large'),
        {..._payload(), 'sha256': 'not a hash'},
      ]) {
        final adapter = _Adapter({
          github: signed(payload),
          cnb: signed(payload),
        });
        expect(await check(adapter), isNull);
        expect(
          adapter.requested.where((url) => url.startsWith('HEAD')),
          isEmpty,
        );
      }
    });

    test('the same or an older build is not offered', () async {
      final adapter = _Adapter({
        github: signed(_payload()),
        cnb: signed(_payload(build: 2026094021)),
      });
      expect(await check(adapter, installed: 2026094022), isNull);
      expect(adapter.requested.where((url) => url.startsWith('HEAD')), isEmpty);
    });

    test('Android reads only its own manifest', () async {
      final adapter = _Adapter({
        github: (status: 200, body: '{}'),
        cnb: (status: 200, body: '{}'),
      });
      final dio = Dio()..httpClientAdapter = adapter;
      expect(await AppUpdateChecker.network(dio).check(1), isNull);
      expect(
        adapter.requested.toSet(),
        updateSources.map((source) => 'GET ${source.api}').toSet(),
      );
      expect(
        updateSources.map((source) => source.api),
        everyElement(endsWith('/update.json')),
      );
    });
  });

  group('Windows installer', () {
    late Directory directory;

    setUp(() {
      directory = Directory.systemTemp.createTempSync('windows-update-test');
      addTearDown(() => directory.deleteSync(recursive: true));
    });

    Map<String, dynamic> release() => {
      'build': 2026094022,
      'sha256': _setupHash,
      'download_url': 'https://github.com/$updateInstallerName',
    };

    test('runs the verified file with the fixed arguments', () async {
      final file = File(p.join(directory.path, 'setup.exe'))
        ..writeAsStringSync('setup');
      final calls = <(String, String)>[];
      final installer = WindowsUpdateInstaller(
        start: (command, arguments) {
          calls.add((command, arguments));
          return true;
        },
      );
      expect(await installer.install(file, release()), 'opened');
      expect(calls, [(file.path, windowsInstallerArguments)]);
    });

    test('a refused elevation can be tried again', () async {
      final file = File(p.join(directory.path, 'setup.exe'))
        ..writeAsStringSync('setup');
      final installer = WindowsUpdateInstaller(start: (_, _) => false);
      expect(await installer.install(file, release()), 'cancelled');
      expect(file.existsSync(), isTrue);
    });

    test('a file changed after the download never runs', () async {
      final file = File(p.join(directory.path, 'setup.exe'))
        ..writeAsStringSync('changed');
      final installer = WindowsUpdateInstaller(
        start: (_, _) => fail('Must not start'),
      );
      await expectLater(
        installer.install(file, release()),
        throwsFormatException,
      );
    });

    test('downloads next to an exe name and refuses a wrong hash', () async {
      final installer = _WindowsInstallerIn(directory);
      final stale = File(p.join(directory.path, 'release-1.exe'))
        ..writeAsStringSync('old');
      final good = UpdateDownload(
        installer: installer,
        transfer: (_, path, _, _) async =>
            File(path).writeAsStringSync('setup'),
      );
      final file = await good.fetch(release(), CancelToken(), (_, _) {}, () {});
      expect(p.basename(file.path), 'release-2026094022.exe');
      expect(stale.existsSync(), isFalse);
      file.deleteSync();

      final bad = UpdateDownload(
        installer: installer,
        transfer: (_, path, _, _) async => File(path).writeAsStringSync('evil'),
      );
      await expectLater(
        bad.fetch(release(), CancelToken(), (_, _) {}, () {}),
        throwsFormatException,
      );
      expect(directory.listSync(), isEmpty);
    });
  });
}

class _WindowsInstallerIn extends WindowsUpdateInstaller {
  final Directory where;

  _WindowsInstallerIn(this.where);

  @override
  Future<Directory> directory() async => where;
}
