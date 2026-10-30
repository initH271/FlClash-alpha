import 'package:fl_clash/common/constant.dart';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('disclaimer', () {
    test('legacy accepted flag counts as accepted', () {
      final props = AppSettingProps.fromJson({'disclaimerAccepted': true});

      expect(props.acceptedDisclaimerVersion, 1);
      expect(disclaimerNeeded(props.acceptedDisclaimerVersion), false);
    });

    test('legacy declined flag still asks', () {
      final props = AppSettingProps.fromJson({'disclaimerAccepted': false});

      expect(props.acceptedDisclaimerVersion, 0);
      expect(disclaimerNeeded(props.acceptedDisclaimerVersion), true);
    });

    test('stored version wins over the legacy flag', () {
      final props = AppSettingProps.fromJson({
        'acceptedDisclaimerVersion': 3,
        'disclaimerAccepted': false,
      });

      expect(props.acceptedDisclaimerVersion, 3);
    });

    test('an older accepted version is never asked again', () {
      expect(disclaimerNeeded(1), false);
      expect(disclaimerNeeded(disclaimerVersion + 1), false);
    });

    test('a fresh install asks', () {
      expect(AppSettingProps.fromJson({}).acceptedDisclaimerVersion, 0);
      expect(disclaimerNeeded(0), true);
    });
  });
}
