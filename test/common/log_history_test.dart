import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:fl_clash/common/log_history.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late Directory dir;
  late String core;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('flclash-logs-test-');
    core = '${dir.path}/core.zip';
    final archive = Archive()
      ..addFile(ArchiveFile.string('core-test.jsonl', 'core history\n'))
      ..addFile(
        ArchiveFile.string(
          'README.txt',
          'Retention: 14 days by record timestamp; no segment-count limit\n'
              'coverage.txt: core log coverage',
        ),
      );
    await File(core).writeAsBytes(ZipEncoder().encode(archive));
  });

  tearDown(() async => dir.delete(recursive: true));

  test('exports a core archive larger than the Android heap', () async {
    const size = 320 * 1024 * 1024;
    final payload = File('${dir.path}/large.jsonl');
    final handle = await payload.open(mode: FileMode.write);
    await handle.truncate(size);
    await handle.setPosition(size - 4);
    await handle.writeString('tail');
    await handle.close();
    final stream = InputFileStream(payload.path);
    final encoder = ZipFileEncoder()..create(core);
    try {
      encoder.addArchiveFile(
        ArchiveFile.stream('core-large.jsonl', stream)
          ..compression = CompressionType.none,
      );
    } finally {
      await encoder.close();
      await stream.close();
    }
    final history = AppLogHistory(() async => Directory('${dir.path}/app'));
    history.add('info', 'APP snapshot');
    final output = await history.exportAll(core, 'recent');
    expect(await File(output).length(), greaterThan(size));
    final archiveStream = InputFileStream(output);
    try {
      final archive = ZipDecoder().decodeStream(archiveStream);
      final entry = archive.findFile('core-large.jsonl')!;
      expect(entry.size, size);
      final extracted = File('${dir.path}/extracted.jsonl');
      final destination = OutputFileStream(extracted.path);
      try {
        entry.writeContent(destination);
      } finally {
        await destination.close();
      }
      expect(
        await sha256.bind(extracted.openRead()).first,
        await sha256.bind(payload.openRead()).first,
      );
      expect(archive.findFile('recent-ui.log'), isNotNull);
    } finally {
      await archiveStream.close();
    }
  }, timeout: const Timeout(Duration(minutes: 2)));

  test(
    'one archive includes core, APP history beyond 5000, and UI snapshot',
    () async {
      final history = AppLogHistory(() async => Directory('${dir.path}/app'));
      for (var i = 0; i < 5100; i++) {
        history.add('info', 'APP record $i');
        if (i % 500 == 0) await history.flush();
      }
      await history.flush();
      final restarted = AppLogHistory(() async => Directory('${dir.path}/app'));
      restarted.add('error', 'after restart\nsecond line');
      final output = await restarted.exportAll(core, 'recent UI');
      final archive = ZipDecoder().decodeBytes(
        await File(output).readAsBytes(),
      );
      expect(
        utf8.decode(archive.findFile('core-test.jsonl')!.content),
        'core history\n',
      );
      expect(
        utf8.decode(archive.findFile('recent-ui.log')!.content),
        'recent UI',
      );
      final readme = utf8.decode(archive.findFile('README.txt')!.content);
      expect(readme, contains('Retention: 14 days by record timestamp'));
      expect(readme, isNot(contains('20 files of 5 MiB')));
      expect(readme, contains('coverage.txt:'));
      expect(readme, contains('not the full day'));
      final app = archive.files
          .where((f) => f.name.startsWith('app/'))
          .map((f) => utf8.decode(f.content))
          .join();
      final records = const LineSplitter()
          .convert(app)
          .map((line) => jsonDecode(line) as Map)
          .toList();
      expect(records, hasLength(5101));
      expect(records.first['message'], 'APP record 0');
      expect(records.last['message'], 'after restart\nsecond line');
    },
  );

  test(
    'rotation bounds files and restart repairs a partial final line',
    () async {
      final appDir = Directory('${dir.path}/app');
      final history = AppLogHistory(
        () async => appDir,
        maxBytes: 256,
        maxFiles: 2,
      );
      for (var i = 0; i < 20; i++) {
        history.add('info', 'record $i');
      }
      await history.flush();
      final files = (await appDir.list().toList()).cast<File>()
        ..sort((a, b) => a.path.compareTo(b.path));
      expect(files, hasLength(2));
      for (final file in files) {
        expect(await file.length(), lessThanOrEqualTo(256));
      }
      await files.last.writeAsString('incomplete', mode: FileMode.append);
      final restarted = AppLogHistory(
        () async => appDir,
        maxBytes: 256,
        maxFiles: 2,
      );
      restarted.add('info', 'recovered');
      await restarted.flush();
      final output = await restarted.exportAll(core, '');
      final archive = ZipDecoder().decodeBytes(
        await File(output).readAsBytes(),
      );
      final text = archive.files
          .where((f) => f.name.startsWith('app/'))
          .map((f) => utf8.decode(f.content))
          .join();
      expect(text, isNot(contains('incomplete')));
      expect(text, contains('recovered'));
    },
  );

  test(
    'failed archive can be retried without poisoning APP recording',
    () async {
      final history = AppLogHistory(() async => Directory('${dir.path}/app'));
      history.add('info', 'before');
      await expectLater(
        history.exportAll('${dir.path}/missing.zip', ''),
        throwsA(isA<FileSystemException>()),
      );
      history.add('info', 'after');
      final output = await history.exportAll(core, '');
      final archive = ZipDecoder().decodeBytes(
        await File(output).readAsBytes(),
      );
      final text = archive.files
          .where((f) => f.name.startsWith('app/'))
          .map((f) => utf8.decode(f.content))
          .join();
      expect(text, contains('before'));
      expect(text, contains('after'));
    },
  );

  test(
    'disk failures fail complete export instead of silently omitting APP logs',
    () async {
      final history = AppLogHistory(
        () async => throw const FileSystemException('disk failed'),
      );
      history.add('info', 'lost');
      await expectLater(history.exportAll(core, 'recent'), throwsStateError);
      expect(await File('$core.all.zip').exists(), isFalse);
    },
  );
}
