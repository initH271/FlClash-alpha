import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'package:flutter_test/flutter_test.dart';

class _TraceAdapter implements HttpClientAdapter {
  _TraceAdapter(this.trace);
  final String trace;
  int calls = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls++;
    return ResponseBody.fromString(
      trace,
      200,
      headers: {
        Headers.contentTypeHeader: ['text/plain'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  test(
    'trace-based regional restriction is distinct from a failed probe',
    () async {
      final adapter = _TraceAdapter('ip=1.2.3.4\nloc=CN\ncolo=HKG\nwarp=off\n');
      final checker = MediaUnlockChecker(
        unifiedDelay: false,
        createClient: (options) => Dio(options)..httpClientAdapter = adapter,
      );
      final result = await checker.checkPlatform(MediaPlatform.openai);
      expect(result.status, MediaUnlockStatus.blocked);
      expect(result.region, 'CN');
      expect(adapter.calls, greaterThan(0));
    },
  );

  test('successful regional probe retains trace details', () async {
    final adapter = _TraceAdapter('ip=1.2.3.4\nloc=US\ncolo=LAX\nwarp=on\n');
    final checker = MediaUnlockChecker(
      unifiedDelay: false,
      createClient: (options) => Dio(options)..httpClientAdapter = adapter,
    );
    final result = await checker.checkPlatform(MediaPlatform.openai);
    expect(result.status, MediaUnlockStatus.unlocked);
    expect(result.region, 'US');
    expect(result.colo, 'LAX');
  });
}
