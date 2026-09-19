import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;

class UpdateInstaller {
  static const channel = MethodChannel('com.follow.clash/update');

  const UpdateInstaller();

  Future<Directory> directory() async =>
      Directory((await channel.invokeMethod<String>('directory'))!);

  Future<void> validate(File file, Map<String, dynamic> release) async {
    await channel.invokeMethod<bool>('validate', _arguments(file, release));
  }

  Future<bool> canInstall() async =>
      await channel.invokeMethod<bool>('canInstall') ?? false;

  Future<String> install(File file, Map<String, dynamic> release) async =>
      (await channel.invokeMethod<String>(
        'install',
        _arguments(file, release),
      ))!;

  Map<String, dynamic> _arguments(File file, Map<String, dynamic> release) => {
    'path': file.path,
    'build': release['build'],
    'sha256': release['sha256'],
  };
}

typedef UpdateTransfer =
    Future<void> Function(
      String url,
      String path,
      CancelToken token,
      ProgressCallback progress,
    );

class UpdateDownload {
  final UpdateInstaller installer;
  final UpdateTransfer transfer;

  UpdateDownload({required this.installer, required this.transfer});

  factory UpdateDownload.network(Dio dio, UpdateInstaller installer) =>
      UpdateDownload(
        installer: installer,
        transfer: (url, path, token, progress) async {
          await dio.download(
            url,
            path,
            cancelToken: token,
            onReceiveProgress: (received, total) {
              if (received > 256 * 1024 * 1024 || total > 256 * 1024 * 1024) {
                token.cancel('Update exceeds size limit');
              }
              progress(received, total);
            },
            options: Options(receiveTimeout: const Duration(seconds: 45)),
          );
        },
      );

  Future<File> fetch(
    Map<String, dynamic> release,
    CancelToken token,
    ProgressCallback progress,
    void Function() verifying, {
    void Function(String)? onSource,
  }) async {
    _checkCancelled(token);
    final build = release['build'] as int;
    final expectedHash = release['sha256'] as String;
    if (build <= 0 || !RegExp(r'^[0-9a-f]{64}$').hasMatch(expectedHash)) {
      throw const FormatException('Invalid release metadata');
    }
    final directory = await installer.directory();
    await directory.create(recursive: true);
    final file = File(p.join(directory.path, 'release-$build.apk'));
    final partial = File('${file.path}.part');
    for (final entity in await directory.list(followLinks: false).toList()) {
      if (entity is File &&
          entity.path != file.path &&
          RegExp(
            r'^release-\d+\.apk(?:\.part)?$',
          ).hasMatch(p.basename(entity.path))) {
        await entity.delete();
      }
    }
    if (await file.exists()) {
      verifying();
      if (await _hash(file) == expectedHash) {
        try {
          await installer.validate(file, release);
          _checkCancelled(token);
          return file;
        } catch (_) {
          await file.delete();
          _checkCancelled(token);
        }
      } else {
        await file.delete();
      }
    }
    final urls = List<String>.from(
      release['download_urls'] as List? ?? [release['download_url']],
    );
    Object? failure;
    for (final url in urls) {
      _checkCancelled(token);
      try {
        onSource?.call(Uri.parse(url).host == 'cnb.cool' ? 'CNB' : 'GitHub');
        await transfer(url, partial.path, token, progress);
        _checkCancelled(token);
        verifying();
        if (await _hash(partial) != expectedHash) {
          throw const FormatException('Update checksum mismatch');
        }
        await partial.rename(file.path);
        await installer.validate(file, release);
        _checkCancelled(token);
        return file;
      } catch (error) {
        failure = error;
        if (await partial.exists()) await partial.delete();
        if (await file.exists()) await file.delete();
        _checkCancelled(token);
        if (error is PlatformException) rethrow;
      }
    }
    if (failure is Exception) throw failure;
    if (failure is Error) throw failure;
    throw const FormatException('No update source available');
  }

  void _checkCancelled(CancelToken token) {
    if (token.isCancelled) throw token.cancelError!;
  }

  Future<String> _hash(File file) async =>
      (await sha256.bind(file.openRead()).first).toString();
}
