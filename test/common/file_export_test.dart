import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:fl_clash/common/picker.dart';
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

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('flclash-file-export-');
    oldPicker = FilePickerPlatform.instance;
    oldPaths = PathProviderPlatform.instance;
    platform = _FilePicker();
    FilePickerPlatform.instance = platform;
    PathProviderPlatform.instance = _Paths(dir.path);
  });

  tearDown(() async {
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
}
