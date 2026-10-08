import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

final appLogHistory = AppLogHistory(
  () async => Directory(
    p.join((await getApplicationSupportDirectory()).path, 'app-log-history'),
  ),
);

class AppLogHistory {
  AppLogHistory(
    this.directory, {
    this.maxBytes = 5 * 1024 * 1024,
    this.maxFiles = 10,
  });

  final Future<Directory> Function() directory;
  final int maxBytes;
  final int maxFiles;
  Future<void> _pending = Future.value();
  Object? _error;
  int _queued = 0;
  int _dropped = 0;
  File? _current;
  int _size = 0;
  int _stamp = 0;
  bool _ready = false;

  Future<T> _serial<T>(Future<T> Function() action) {
    final next = _pending.then((_) => action());
    _pending = next.then<void>((_) {}, onError: (Object _) {});
    return next;
  }

  void add(String level, String message) {
    if (_queued >= 1024) {
      _dropped++;
      return;
    }
    final record = jsonEncode({
      'time': DateTime.now().toUtc().toIso8601String(),
      'level': level,
      'message': message.length > 32768
          ? '${message.substring(0, 32768)} [truncated]'
          : message,
    });
    _queued++;
    unawaited(
      _serial(() async {
        try {
          await _write('$record\n');
          if (_dropped > 0) {
            final count = _dropped;
            _dropped = 0;
            await _write(
              '${jsonEncode({'time': DateTime.now().toUtc().toIso8601String(), 'level': 'warning', 'message': '[APP] $count records dropped because the disk queue was full'})}\n',
            );
          }
        } catch (error) {
          _error ??= error;
          rethrow;
        } finally {
          _queued--;
        }
      }).catchError((Object _) {}),
    );
  }

  Future<List<File>> _files() async {
    final dir = await directory();
    await dir.create(recursive: true);
    final files = await dir
        .list()
        .where(
          (entry) =>
              entry is File &&
              RegExp(r'^app-\d{20}\.jsonl$').hasMatch(p.basename(entry.path)),
        )
        .cast<File>()
        .toList();
    files.sort((a, b) => a.path.compareTo(b.path));
    return files;
  }

  Future<void> _write(String line) async {
    final bytes = utf8.encode(line);
    if (bytes.length > maxBytes) {
      throw StateError('APP log record exceeds segment size');
    }
    if (!_ready) {
      final files = await _files();
      if (files.isNotEmpty) {
        _current = files.last;
        _stamp = int.parse(
          p.basenameWithoutExtension(_current!.path).substring(4),
        );
        final data = await _current!.readAsBytes();
        var end = data.length;
        while (end > 0 && data[end - 1] != 10) {
          end--;
        }
        if (end != data.length) {
          final handle = await _current!.open(mode: FileMode.append);
          try {
            await handle.truncate(end);
          } finally {
            await handle.close();
          }
        }
        _size = end;
      }
      _ready = true;
    }
    if (_current == null || _size + bytes.length > maxBytes) {
      final now = DateTime.now().microsecondsSinceEpoch;
      _stamp = now > _stamp ? now : _stamp + 1;
      _current = File(
        p.join(
          (await directory()).path,
          'app-${_stamp.toString().padLeft(20, '0')}.jsonl',
        ),
      );
      await _current!.create();
      _size = 0;
      final files = await _files();
      for (final file in files.take(
        files.length > maxFiles ? files.length - maxFiles : 0,
      )) {
        await file.delete();
      }
    }
    await _current!.writeAsBytes(bytes, mode: FileMode.append);
    _size += bytes.length;
  }

  Future<String> exportAll(String corePath, String recentLogs) =>
      _serial(() async {
        if (_error != null) {
          throw StateError('APP log history write failed: $_error');
        }
        final files = await _files();
        final output = '$corePath.all.zip';
        await compute(_combineLogs, (
          corePath: corePath,
          appPaths: files.map((f) => f.path).toList(),
          recentLogs: recentLogs,
          output: output,
        ));
        return output;
      });

  Future<void> flush() => _serial(() async {
    if (_error != null) {
      throw StateError('APP log history write failed: $_error');
    }
  });
}

Future<void> _combineLogs(
  ({String corePath, List<String> appPaths, String recentLogs, String output})
  input,
) async {
  final output = File(input.output);
  try {
    final source = InputFileStream(input.corePath);
    try {
      final archive = ZipDecoder().decodeStream(source);
      final readme = archive.findFile('README.txt');
      final coreDescription = readme == null
          ? 'FlClash core log history\n'
          : utf8.decode(readme.content);
      final encoder = ZipFileEncoder()..create(input.output);
      try {
        for (final file in archive.files) {
          if (file.name != 'README.txt') encoder.addArchiveFile(file);
        }
        for (final path in input.appPaths) {
          await encoder.addFile(
            File(path),
            p.join('app', p.basename(path)).replaceAll('\\', '/'),
          );
        }
        encoder.addArchiveFile(
          ArchiveFile.string('recent-ui.log', input.recentLogs),
        );
        encoder.addArchiveFile(
          ArchiveFile.string(
            'README.txt',
            '${coreDescription.trimRight()}\n\n'
                'app/*.jsonl: rolling APP history, 10 files of 5 MiB\n'
                'recent-ui.log: UI snapshot at export, only the latest in-memory lines; '
                'it overlaps core and APP history and is not the full day\n'
                'Older records expire. Records before this build was installed cannot be recovered.\n',
          ),
        );
      } finally {
        await encoder.close();
      }
    } finally {
      await source.close();
    }
  } catch (_) {
    if (await output.exists()) await output.delete();
    rethrow;
  }
}
