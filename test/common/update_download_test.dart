import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

class _Installer extends UpdateInstaller {
  final Directory root;
  int validations = 0;
  bool reject = false;

  _Installer(this.root);

  @override
  Future<Directory> directory() async => root;

  @override
  Future<void> validate(File file, Map<String, dynamic> release) async {
    validations++;
    if (reject) throw PlatformException(code: 'UPDATE_INVALID');
  }
}

void main() {
  late Directory root;
  late _Installer installer;
  late Map<String, dynamic> release;
  final bytes = [1, 2, 3, 4];

  setUp(() async {
    root = await Directory.systemTemp.createTemp('flclash-update-');
    installer = _Installer(root);
    release = {
      'build': 10,
      'sha256': sha256.convert(bytes).toString(),
      'download_urls': ['https://cnb.cool/first', 'https://github.com/second'],
    };
  });
  tearDown(() => root.delete(recursive: true));

  test(
    'atomic download verifies hash and native identity before ready',
    () async {
      final download = UpdateDownload(
        installer: installer,
        transfer: (url, path, token, progress) async {
          expect(path, endsWith('.part'));
          await File(path).writeAsBytes(bytes);
          progress(4, 4);
        },
      );
      final file = await download.fetch(
        release,
        CancelToken(),
        (_, _) {},
        () {},
      );
      expect(await file.readAsBytes(), bytes);
      expect(await File('${file.path}.part').exists(), isFalse);
      expect(installer.validations, 1);
    },
  );

  test('verified cached APK avoids a second transfer', () async {
    await File('${root.path}/release-10.apk').writeAsBytes(bytes);
    final download = UpdateDownload(
      installer: installer,
      transfer: (_, _, _, _) async => fail('Cache should be reused'),
    );
    await download.fetch(release, CancelToken(), (_, _) {}, () {});
    expect(installer.validations, 1);
  });

  test('corrupt first mirror falls back to the second', () async {
    final visited = <String>[];
    final download = UpdateDownload(
      installer: installer,
      transfer: (url, path, token, progress) async {
        visited.add(url);
        await File(path).writeAsBytes(visited.length == 1 ? [9] : bytes);
      },
    );
    final file = await download.fetch(release, CancelToken(), (_, _) {}, () {});
    expect(visited.length, 2);
    expect(await file.readAsBytes(), bytes);
  });

  test('closing cancels and removes the incomplete download', () async {
    final token = CancelToken();
    final download = UpdateDownload(
      installer: installer,
      transfer: (_, path, token, _) async {
        await File(path).writeAsBytes([1]);
        token.cancel('closed');
      },
    );
    await expectLater(
      download.fetch(release, token, (_, _) {}, () {}),
      throwsA(isA<DioException>()),
    );
    expect(await root.list().toList(), isEmpty);
    expect(installer.validations, 0);
  });

  test(
    'native package or signer rejection never leaves an installable file',
    () async {
      installer.reject = true;
      var transfers = 0;
      final download = UpdateDownload(
        installer: installer,
        transfer: (_, path, _, _) async {
          transfers++;
          await File(path).writeAsBytes(bytes);
        },
      );
      await expectLater(
        download.fetch(release, CancelToken(), (_, _) {}, () {}),
        throwsA(isA<PlatformException>()),
      );
      expect(transfers, 1);
      expect(await root.list().toList(), isEmpty);
    },
  );
}
