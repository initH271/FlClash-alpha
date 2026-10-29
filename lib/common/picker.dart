import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/plugins/app.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

class Picker {
  Picker({App? androidApp}) : _androidApp = androidApp ?? app;

  final App? _androidApp;

  Future<PlatformFile?> pickerFile() async {
    return FilePicker.pickFile(initialDirectory: await appPath.downloadDirPath);
  }

  Future<Uri?> saveFile(String fileName, Uint8List bytes) async {
    final uri = await FilePicker.saveFile(
      fileName: fileName,
      initialDirectory: await appPath.downloadDirPath,
      bytes: bytes,
    );
    if (!system.isAndroid && uri != null && uri.scheme == 'file') {
      final file = File(uri.toFilePath());
      await file.safeWriteAsBytes(bytes);
    }
    return uri;
  }

  Future<Uri?> saveFileWithPath(String fileName, String localPath) async {
    final localFile = File(localPath);
    if (!await localFile.exists()) {
      throw FileSystemException('Export source does not exist', localPath);
    }
    try {
      final androidApp = _androidApp;
      final uri = androidApp != null
          ? await androidApp.createExportDocument(fileName)
          : await FilePicker.saveFile(
              fileName: fileName,
              initialDirectory: await appPath.downloadDirPath,
              bytes: Uint8List(0),
            );
      if (uri == null) return null;
      if (androidApp != null) {
        await androidApp.copyFileToUri(localPath, uri);
      } else {
        await localFile.copy(uri.toFilePath());
      }
      return uri;
    } finally {
      await localFile.safeDelete();
    }
  }

  Future<String?> pickerConfigQRCode() async {
    final xFile = await ImagePicker().pickImage(source: ImageSource.gallery);
    if (xFile == null) {
      return null;
    }
    // Not through a throwaway MobileScannerController: disposing one clears
    // the platform scan window of a scanner page that is still open.
    final capture = await MobileScannerPlatform.instance.analyzeImage(
      xFile.path,
      formats: const [BarcodeFormat.qrCode],
    );
    final url = profileUrlFromQrCodes(
      capture?.barcodes.map((barcode) => barcode.rawValue) ?? const [],
    );
    if (url == null) {
      throw MessageException(currentAppLocalizations.pleaseUploadValidQrcode);
    }
    return url;
  }
}

extension PlatformFileExt on PlatformFile {
  Future<Uint8List> readBytes() {
    return readAsBytes();
  }
}

final picker = Picker();
