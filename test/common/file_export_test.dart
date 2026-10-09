import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:fl_clash/common/picker.dart';
import 'package:fl_clash/common/constant.dart';
import 'package:fl_clash/plugins/app.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';

class _Paths extends PathProviderPlatform {
  _Paths(this.root);
  final String root;

  @override
  Future<String?> getDownloadsPath() async => root;

  @override
  Future<String?> getApplicationSupportPath() async => root;

  @override
  Future<String?> getTemporaryPath() async => root;

  @override
  Future<String?> getApplicationCachePath() async => root;
}

class _FilePicker extends FilePickerPlatform {
  Uri? destination;
  Uint8List? received;
  Exception? error;

  @override
  Future<Uri?> saveFile({
    required String fileName,
    required Uint8List bytes,
    required String mimeType,
    String? dialogTitle,
    String? initialDirectory,
    Function(FilePickerStatus)? onFileSaving,
    WindowsOptions windowsOptions = const WindowsOptions(),
    LinuxOptions linuxOptions = const LinuxOptions(),
    WebOptions webOptions = const WebOptions(),
  }) async {
    if (error != null) throw error!;
    received = bytes;
    return destination;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory dir;
  late _FilePicker platform;
  late FilePickerPlatform oldPicker;
  late PathProviderPlatform oldPaths;
  const channel = MethodChannel('$packageName/app');

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('flclash-file-export-');
    oldPicker = FilePickerPlatform.instance;
    oldPaths = PathProviderPlatform.instance;
    platform = _FilePicker();
    FilePickerPlatform.instance = platform;
    PathProviderPlatform.instance = _Paths(dir.path);
  });

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    FilePickerPlatform.instance = oldPicker;
    PathProviderPlatform.instance = oldPaths;
    await dir.delete(recursive: true);
  });

  test('file exports transfer no payload through the picker channel', () async {
    final source = File('${dir.path}/source.zip');
    final bytes = Uint8List(2 * 1024 * 1024)..last = 42;
    await source.writeAsBytes(bytes);
    final destination = File('${dir.path}/saved.zip');
    platform.destination = destination.uri;
    expect(
      await Picker().saveFileWithPath('saved.zip', source.path),
      destination.uri,
    );
    expect(platform.received, isEmpty);
    expect(await destination.readAsBytes(), bytes);
    expect(await source.exists(), isFalse);
  });

  test('cancel removes only the temporary source', () async {
    final source = File('${dir.path}/source.zip');
    await source.writeAsString('temporary');
    expect(await Picker().saveFileWithPath('saved.zip', source.path), isNull);
    expect(await source.exists(), isFalse);
  });

  test(
    'Android export streams to the complete selected document URI',
    () async {
      final source = File('${dir.path}/source.zip');
      await source.writeAsString('archive');
      const destination = 'content://downloads/document/msf%3A86';
      final calls = <MethodCall>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            calls.add(call);
            if (call.method == 'createExportDocument') return destination;
            expect(await source.exists(), isTrue);
            return null;
          });
      final uri = await Picker(
        androidApp: App(),
      ).saveFileWithPath('history.zip', source.path);
      expect(uri.toString(), destination);
      expect(calls.map((call) => call.method), [
        'createExportDocument',
        'copyFileToUri',
      ]);
      expect(calls.last.arguments, {'path': source.path, 'uri': destination});
      expect(platform.received, isNull);
      expect(await source.exists(), isFalse);
    },
  );

  test('Android cancellation does not copy an archive', () async {
    final source = File('${dir.path}/source.zip');
    await source.writeAsString('archive');
    final methods = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          methods.add(call.method);
          return null;
        });
    expect(
      await Picker(
        androidApp: App(),
      ).saveFileWithPath('history.zip', source.path),
      isNull,
    );
    expect(methods, ['createExportDocument']);
    expect(await source.exists(), isFalse);
  });

  test(
    'Android copy failure reaches the caller and cleans up the archive',
    () async {
      final source = File('${dir.path}/source.zip');
      await source.writeAsString('archive');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'createExportDocument') {
              return 'content://downloads/document/86';
            }
            throw PlatformException(code: 'PLATFORM_ERROR');
          });
      await expectLater(
        Picker(androidApp: App()).saveFileWithPath('history.zip', source.path),
        throwsA(isA<PlatformException>()),
      );
      expect(await source.exists(), isFalse);
    },
  );

  for (final code in ['NO_ACTIVITY', 'EXPORT_PENDING']) {
    test('Android picker $code cleans up without starting a copy', () async {
      final source = File('${dir.path}/source.zip');
      await source.writeAsString('archive');
      final methods = <String>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            methods.add(call.method);
            throw PlatformException(code: code);
          });
      await expectLater(
        Picker(androidApp: App()).saveFileWithPath('history.zip', source.path),
        throwsA(
          isA<PlatformException>().having((error) => error.code, 'code', code),
        ),
      );
      expect(methods, ['createExportDocument']);
      expect(await source.exists(), isFalse);
    });
  }

  test(
    'a failed destination choice still removes the temporary source',
    () async {
      final source = File('${dir.path}/source.zip');
      await source.writeAsString('temporary');
      platform.error = const FileSystemException('destination unavailable');
      await expectLater(
        Picker().saveFileWithPath('saved.zip', source.path),
        throwsA(isA<FileSystemException>()),
      );
      expect(await source.exists(), isFalse);
    },
  );
}
