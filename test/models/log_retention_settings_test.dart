import 'dart:convert';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('old app settings default to two weeks', () {
    expect(AppSettingProps.fromJson({}).logRetentionDays, 14);
  });
  test('presets and custom days round trip through saved JSON', () {
    for (final days in [1, 7, 14, 30, 21, 36500]) {
      final value = AppSettingProps(logRetentionDays: days);
      final restored = AppSettingProps.fromJson(
        jsonDecode(jsonEncode(value)) as Map<String, dynamic>,
      );
      expect(restored.logRetentionDays, days);
    }
  });
  test(
    'invalid retention alone restores default without erasing other settings',
    () {
      for (final invalid in [0, -1, 36501, 'bad', 2.5]) {
        final value = AppSettingProps.fromJson({
          'logRetentionDays': invalid,
          'openLogs': true,
        });
        expect(value.logRetentionDays, 14);
        expect(value.openLogs, isTrue);
      }
    },
  );
}
