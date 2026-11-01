import 'dart:io';

import 'package:fl_clash/common/common.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart';

void main() {
  late Directory root;

  setUp(() {
    root = Directory.systemTemp.createTempSync('file_test');
  });

  tearDown(() {
    if (root.existsSync()) {
      root.deleteSync(recursive: true);
    }
  });

  group('safeDelete', () {
    test('accepts a file that is already gone', () async {
      await expectLater(
        File(join(root.path, 'missing')).safeDelete(),
        completes,
      );
    });

    test('removes a file', () async {
      final file = File(join(root.path, 'a'))..writeAsStringSync('x');

      await file.safeDelete();

      expect(file.existsSync(), isFalse);
    });

    test('lets overlapping deletes of the same file both succeed', () async {
      for (var i = 0; i < 300; i++) {
        final file = File(join(root.path, 'race$i'))..writeAsStringSync('x');

        await Future.wait([file.safeDelete(), file.safeDelete()]);

        expect(file.existsSync(), isFalse);
      }
    });

    test('lets overlapping recursive deletes of a directory succeed', () async {
      for (var i = 0; i < 100; i++) {
        final dir = Directory(join(root.path, 'dir$i'));
        for (var j = 0; j < 20; j++) {
          File(join(dir.path, 'sub', 'f$j')).createSync(recursive: true);
        }

        await Future.wait([
          dir.safeDelete(recursive: true),
          dir.safeDelete(recursive: true),
        ]);

        expect(dir.existsSync(), isFalse);
      }
    });

    test('does nothing when the path is of the other type', () async {
      final dir = Directory(join(root.path, 'd'))..createSync();
      final file = File(join(root.path, 'f'))..writeAsStringSync('x');

      await File(dir.path).safeDelete();
      await Directory(file.path).safeDelete();

      expect(dir.existsSync(), isTrue);
      expect(file.existsSync(), isTrue);
    });

    test('still throws other failures', () async {
      final dir = Directory(join(root.path, 'full'));
      File(join(dir.path, 'f')).createSync(recursive: true);

      await expectLater(
        dir.safeDelete(),
        throwsA(
          isA<FileSystemException>().having(
            (e) => e is PathNotFoundException,
            'is PathNotFoundException',
            isFalse,
          ),
        ),
      );
      expect(dir.existsSync(), isTrue);
    });
  });

  group('safeDeletePath', () {
    test('removes a file', () async {
      final path = join(root.path, 'config.yaml');
      File(path).writeAsStringSync('mixed-port: 7890');

      await safeDeletePath(path);

      expect(File(path).existsSync(), isFalse);
    });

    test('removes a directory along with everything under it', () async {
      final path = join(root.path, '42');
      File(join(path, 'proxies', 'abc'))
        ..createSync(recursive: true)
        ..writeAsStringSync('proxies: []');

      await safeDeletePath(path);

      expect(Directory(path).existsSync(), isFalse);
    });

    test('accepts a path that is already gone', () async {
      await expectLater(safeDeletePath(join(root.path, 'missing')), completes);
    });
  });

  group('writeAsStringAtomically', () {
    test('replaces the file and leaves nothing beside it', () async {
      final file = File(join(root.path, 'config.yaml'))
        ..writeAsStringSync('mixed-port: 7890');

      await file.writeAsStringAtomically('mixed-port: 7891');

      expect(file.readAsStringSync(), 'mixed-port: 7891');
      expect(root.listSync().map((entry) => basename(entry.path)), [
        'config.yaml',
      ]);
    });

    test('creates the directory a first write needs', () async {
      final file = File(join(root.path, 'home', 'config.yaml'));

      await file.writeAsStringAtomically('mode: rule');

      expect(file.readAsStringSync(), 'mode: rule');
    });

    test('keeps the old file when the new one cannot be written', () async {
      final file = File(join(root.path, 'config.yaml'))
        ..writeAsStringSync('mode: rule');
      Directory('${file.path}.$pid.tmp').createSync();

      await expectLater(
        file.writeAsStringAtomically('mode: global'),
        throwsA(isA<FileSystemException>()),
      );
      expect(file.readAsStringSync(), 'mode: rule');
    });
  });
}
