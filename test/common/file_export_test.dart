import 'dart:io';

import 'package:fl_clash/common/common.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

const channel = MethodChannel('$packageName/app');

typedef _Chunks = List<({Uint8List bytes, bool first, bool done})>;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory dir;
  late _Chunks chunks;
  late List<MethodCall> calls;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('flclash-file-export-');
    chunks = [];
    calls = [];
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    await dir.delete(recursive: true);
  });

  void answerNative({
    String? destination,
    Map<String, Object?> extra = const {},
    PlatformException? Function(MethodCall call)? fail,
  }) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          final error = fail?.call(call);
          if (error != null) {
            throw error;
          }
          switch (call.method) {
            case 'createExportDocument':
              return destination;
            case 'writeExportChunk':
              chunks.add((
                bytes: (call.arguments['bytes'] as Uint8List),
                first: call.arguments['first'] as bool,
                done: call.arguments['done'] as bool,
              ));
              return null;
            default:
              return extra[call.method];
          }
        });
  }

  Future<File> source(int size) async {
    final file = File('${dir.path}/FlClash_logs.zip');
    await file.writeAsBytes(Uint8List(size)..[size - 1] = 42);
    return file;
  }

  test('a content document keeps its scheme and authority', () async {
    answerNative(destination: 'content://com.android.providers/downloads/folder/1');
    final file = await source(1024);

    final uri = await exportFileToDocument(
      fileName: 'FlClash_logs.zip',
      source: file,
      initialUri: (_) => Uri.parse('content://com.android.externalstorage.documents/document/primary%3ADownload'),
      android: true,
    );

    expect(uri.toString(), 'content://com.android.providers/downloads/folder/1');
    expect(uri!.scheme, 'content');
    expect(uri.authority, 'com.android.providers');
    expect(calls.first.method, 'createExportDocument');
    expect(calls.first.arguments['fileName'], 'FlClash_logs.zip');
  });

  test('the archive is streamed in bounded chunks and never posted whole', () async {
    answerNative(destination: 'content://provider/document/1');
    final file = await source(exportChunkSize + 100);

    await exportFileToDocument(
      fileName: 'FlClash_logs.zip',
      source: file,
      initialUri: (_) => null,
      android: true,
    );

    final writes = chunks.where((chunk) => !chunk.done).toList();
    expect(writes.length, 2);
    expect(writes.first.bytes.length, exportChunkSize);
    expect(writes.first.first, isTrue);
    expect(writes.last.bytes.length, 100);
    expect(writes.last.first, isFalse);
    expect(writes.first.bytes.length + writes.last.bytes.length, exportChunkSize + 100);
    for (final call in calls.where((c) => c.method == 'writeExportChunk')) {
      expect((call.arguments['bytes'] as Uint8List).length, lessThanOrEqualTo(exportChunkSize));
    }
    // Only the destination and the file name travel on the channel.
    expect(calls.where((call) => call.method == 'writeExportChunk'), isNotEmpty);
    expect(calls.first.method, 'createExportDocument');
    expect(chunks.last.done, isTrue);
    expect(chunks.last.bytes, isEmpty);
  });

  test('a destination without a scheme is refused instead of saved privately', () async {
    answerNative(destination: 'folder/1');
    final file = await source(16);

    await expectLater(
      exportFileToDocument(
        fileName: 'FlClash_logs.zip',
        source: file,
        initialUri: (_) => null,
        android: true,
      ),
      throwsA(
        isA<ExportException>().having(
          (error) => error.failure,
          'failure',
          ExportFailure.writeFailed,
        ),
      ),
    );
    expect(chunks, isEmpty);
  });

  test('a dismissed dialog is reported as cancelled', () async {
    answerNative();
    final file = await source(16);

    await expectLater(
      exportFileToDocument(
        fileName: 'FlClash_logs.zip',
        source: file,
        initialUri: (_) => null,
        android: true,
      ),
      throwsA(
        isA<ExportException>().having(
          (error) => error.failure,
          'failure',
          ExportFailure.cancelled,
        ),
      ),
    );
    expect(chunks, isEmpty);
  });

  test('a missing provider is reported as unavailable', () async {
    answerNative(
      fail: (call) => call.method == 'createExportDocument'
          ? PlatformException(code: 'EXPORT_NO_PROVIDER', message: 'no explorer')
          : PlatformException(code: 'EXPORT_WRITE_FAILED'),
    );
    final file = await source(16);

    await expectLater(
      exportFileToDocument(
        fileName: 'FlClash_logs.zip',
        source: file,
        initialUri: (_) => null,
        android: true,
      ),
      throwsA(
        isA<ExportException>().having(
          (error) => error.failure,
          'failure',
          ExportFailure.unavailable,
        ),
      ),
    );
  });

  test('a native write failure reaches the caller', () async {
    answerNative(
      destination: 'content://provider/document/1',
      fail: (call) => call.method == 'writeExportChunk'
          ? PlatformException(code: 'EXPORT_WRITE_FAILED', message: 'read-only')
          : null,
    );
    final file = await source(exportChunkSize * 2);

    await expectLater(
      exportFileToDocument(
        fileName: 'FlClash_logs.zip',
        source: file,
        initialUri: (_) => null,
        android: true,
      ),
      throwsA(
        isA<ExportException>().having(
          (error) => error.failure,
          'failure',
          ExportFailure.writeFailed,
        ),
      ),
    );
  });

  test('a renamed document becomes the destination that receives the bytes', () async {
    answerNative(
      destination: 'content://provider/document/1',
      extra: {
        'renameExportDocument': 'FlClash_logs_2026091401.zip',
      },
    );
    final file = await source(32);

    final uri = await exportFileToDocument(
      fileName: 'FlClash_logs_2026091401.zip',
      source: file,
      initialUri: (_) => null,
      android: true,
    );

    expect(uri!.path, endsWith('/FlClash_logs_2026091401.zip'));
    final writes = calls.where((call) => call.method == 'writeExportChunk');
    expect(writes, isNotEmpty);
    for (final call in writes) {
      expect(call.arguments['uri'], uri.toString());
    }
  });

  test('an absent source never opens the save dialog', () async {
    answerNative(destination: 'content://provider/document/1');

    await expectLater(
      exportFileToDocument(
        fileName: 'FlClash_logs.zip',
        source: File('${dir.path}/missing.zip'),
        initialUri: (_) => null,
        android: true,
      ),
      throwsA(
        isA<ExportException>().having(
          (error) => error.failure,
          'failure',
          ExportFailure.noArchive,
        ),
      ),
    );
    expect(calls, isEmpty);
  });

  test('desktop forwards the file path and keeps no bytes on the channel', () async {
    answerNative(extra: {'saveExportFile': '${dir.path}/saved.zip'});
    final file = await source(512);

    final uri = await exportFileToDocument(
      fileName: 'saved.zip',
      source: file,
      initialUri: (_) => null,
      android: false,
    );

    expect(uri!.scheme, 'file');
    expect(uri.toFilePath(), '${dir.path}/saved.zip');
    expect(calls.single.method, 'saveExportFile');
    expect(calls.single.arguments, {
      'fileName': 'saved.zip',
      'path': file.path,
    });
  });

  test('partial exports from a superseded attempt are removed', () async {
    await File('${dir.path}/core-all.zip.export-part').writeAsString('stale');
    await File('${dir.path}/kept.zip').writeAsString('kept');

    await cleanExportPartials(dir);

    expect(await File('${dir.path}/core-all.zip.export-part').exists(), isFalse);
    expect(await File('${dir.path}/kept.zip').exists(), isTrue);
  });

  test('document file names drop the directory part', () {
    expect(documentFileName('/data/user/0/com.follow.clash.dev/files/all.zip'), 'all.zip');
  });
}
