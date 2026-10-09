import 'dart:async';
import 'dart:io';

import 'package:fl_clash/common/constant.dart';
import 'package:fl_clash/common/file.dart';
import 'package:flutter/services.dart';

const _channel = MethodChannel('$packageName/app');

/// Bytes handed to a provider at a time; OEM providers reject a whole archive.
const exportChunkSize = 64 * 1024;

enum ExportFailure {
  cancelled('EXPORT_CANCELLED', 'The save dialog was dismissed'),
  unavailable('EXPORT_UNAVAILABLE', 'No document provider can create the file'),
  noArchive('EXPORT_NO_ARCHIVE', 'The log archive could not be prepared'),
  writeFailed('EXPORT_WRITE_FAILED', 'The selected destination rejected the log archive');

  const ExportFailure(this.code, this.message);

  final String code;
  final String message;
}

class ExportException implements Exception {
  const ExportException(this.failure, [this.detail]);

  final ExportFailure failure;
  final String? detail;

  @override
  String toString() => 'ExportException(${failure.code}): ${detail ?? failure.message}';
}

/// Creates [fileName] through ACTION_CREATE_DOCUMENT and streams [source] into
/// it. The dart:io file is the only carrier, and a content URI stays a document
/// handle: `Uri.path` on `content://` drops the authority.
Future<Uri?> exportFileToDocument({
  required String fileName,
  required File source,
  required Uri? Function(Uri) initialUri,
  bool? android,
}) async {
  if (android ?? Platform.isAndroid) {
    return _exportThroughDocument(fileName, source, initialUri);
  }
  final destination = await _channel.invokeMethod<String>('saveExportFile', {
    'fileName': fileName,
    'path': source.absolute.path,
  });
  return destination == null ? null : Uri.file(destination);
}

Future<Uri?> _exportThroughDocument(
  String fileName,
  File source,
  Uri? Function(Uri) initialUri,
) async {
  if (!await source.exists()) {
    throw ExportException(
      ExportFailure.noArchive,
      'Missing export source: ${source.path}',
    );
  }
  final String? destination;
  try {
    destination = await _channel.invokeMethod<String>('createExportDocument', {
      'fileName': fileName,
      'initialUri': initialUri(Uri.file(source.parent.path)).toString(),
    });
  } on PlatformException catch (error) {
    throw ExportException(_platformFailure(error), error.message);
  }
  if (destination == null) {
    throw const ExportException(ExportFailure.cancelled);
  }
  var uri = Uri.tryParse(destination);
  if (uri == null || !uri.hasScheme) {
    // Without a scheme this becomes a private sandbox file that looks saved.
    throw ExportException(
      ExportFailure.writeFailed,
      'Destination URI lost its scheme: $destination',
    );
  }
  uri = await _renameToMatchDestination(uri, fileName);
  await _streamInto(uri, source);
  return uri;
}

/// The provider's answer decides the real destination, so the bytes follow the
/// name the file actually has.
Future<Uri> _renameToMatchDestination(Uri uri, String fileName) async {
  final String? renamed;
  try {
    renamed = await _channel.invokeMethod<String>('renameExportDocument', {
      'uri': uri.toString(),
      'fileName': fileName,
    });
  } on PlatformException catch (error) {
    throw ExportException(ExportFailure.writeFailed, error.message);
  }
  if (renamed == null || renamed.isEmpty) {
    return uri;
  }
  if (renamed == uri.pathSegments.last) {
    return uri;
  }
  return uri.replace(
    path: '${uri.path.replaceFirst(RegExp(r'/[^/]+$'), '')}/$renamed',
  );
}

Future<void> _streamInto(Uri uri, File source) async {
  final handle = await source.open();
  var offset = 0;
  try {
    while (true) {
      final chunk = await handle.read(exportChunkSize);
      if (chunk.isEmpty) {
        break;
      }
      try {
        await _channel.invokeMethod<void>('writeExportChunk', {
          'uri': uri.toString(),
          'bytes': Uint8List.fromList(chunk),
          'first': offset == 0,
          'done': false,
        });
      } on PlatformException catch (error) {
        throw ExportException(ExportFailure.writeFailed, error.message);
      }
      offset += chunk.length;
    }
  } finally {
    await handle.close();
  }
  try {
    await _channel.invokeMethod<void>('writeExportChunk', {
      'uri': uri.toString(),
      'bytes': Uint8List(0),
      'first': false,
      'done': true,
    });
  } on PlatformException catch (error) {
    throw ExportException(ExportFailure.writeFailed, error.message);
  }
}

ExportFailure _platformFailure(PlatformException error) {
  return switch (error.code) {
    'EXPORT_CANCELLED' => ExportFailure.cancelled,
    'EXPORT_NO_PROVIDER' || 'EXPORT_NO_TARGET' => ExportFailure.unavailable,
    _ => ExportFailure.writeFailed,
  };
}

String documentFileName(String path) => path.split(Platform.pathSeparator).last;

Future<void> cleanExportPartials(Directory directory) async {
  if (!await directory.exists()) {
    return;
  }
  await for (final entity in directory.list()) {
    if (entity is File && entity.path.contains('.export-part')) {
      await entity.safeDelete();
    }
  }
}
