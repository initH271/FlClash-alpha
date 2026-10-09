import 'package:fl_clash/common/boot_record.dart';
import 'package:fl_clash/common/constant.dart';
import 'package:fl_clash/plugins/app.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';

class _Paths extends PathProviderPlatform {
  @override
  Future<String?> getDownloadsPath() async => null;

  @override
  Future<String?> getApplicationSupportPath() async => '/tmp';

  @override
  Future<String?> getTemporaryPath() async => '/tmp';

  @override
  Future<String?> getApplicationCachePath() async => '/tmp';
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('$packageName/app');
  late PathProviderPlatform oldPaths;

  setUp(() {
    oldPaths = PathProviderPlatform.instance;
    PathProviderPlatform.instance = _Paths();
    App().clearPackageIconCache();
  });

  test(
    'exports a local file using only paths in the platform message',
    () async {
      MethodCall? received;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            received = call;
            return null;
          });
      await App().copyFileToUri(
        '/private/history.zip',
        Uri.parse('content://logs/1'),
      );
      expect(received!.method, 'copyFileToUri');
      expect(received!.arguments, {
        'path': '/private/history.zip',
        'uri': 'content://logs/1',
      });
    },
  );

  test('a directory is offered to the dialog as a document URI', () async {
    MethodCall? received;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          received = call;
          return 'content://com.android.externalstorage.documents/document/primary%3ADownload';
        });

    final uri = await App().filePickerInitialUri('/storage/emulated/0/Download');

    expect(received!.method, 'getDocumentTreeUri');
    expect(received!.arguments, {'path': '/tmp'});
    expect(uri, Uri.parse('content://com.android.externalstorage.documents/document/primary%3ADownload'));
    expect(uri!.scheme, 'content');
  });

  test('a directory without a document URI leaves the dialog unseeded', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async => null);

    expect(await App().filePickerInitialUri('/data/local/tmp'), isNull);
  });

  test('a failed native copy is surfaced to the export caller', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async {
          throw PlatformException(code: 'PLATFORM_ERROR');
        });
    await expectLater(
      App().copyFileToUri(
        '/private/history.zip',
        Uri.parse('content://logs/1'),
      ),
      throwsA(isA<PlatformException>()),
    );
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
    PathProviderPlatform.instance = oldPaths;
    App().clearPackageIconCache();
  });

  test('reads previous execution crash state from Android', () async {
    MethodCall? receivedCall;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          receivedCall = call;
          return true;
        });

    final didCrash = await App().didCrashOnPreviousExecution();

    expect(didCrash, isTrue);
    expect(receivedCall, isNotNull);
    expect(receivedCall!.method, 'didCrashOnPreviousExecution');
  });

  test('uses false when Android returns no crash state', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async => null);

    expect(await App().didCrashOnPreviousExecution(), isFalse);
  });

  test('requests every package icon from Android only once', () async {
    var iconCallCount = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          iconCallCount++;
          return '/icons/${call.arguments['packageName']}.png';
        });

    final app = App();
    final results = await Future.wait([
      app.getPackageIcon('com.a'),
      app.getPackageIcon('com.a'),
    ]);
    final cached = await app.getPackageIcon('com.a');

    expect(iconCallCount, 1);
    expect(results.first, isNotNull);
    expect(cached, same(results.first));
    expect(app.hasPackageIcon('com.a'), isTrue);
    expect(app.getCachedPackageIcon('com.a'), same(results.first));

    await app.getPackageIcon('com.b');

    expect(iconCallCount, 2);
  });

  test(
    'falls back to the default activity icon for unknown packages',
    () async {
      final requested = <String?>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            final packageName = call.arguments['packageName'] as String?;
            requested.add(packageName);
            return packageName == '' ? '/icons/default_icon.webp' : null;
          });

      final app = App();

      final fallback = await app.getPackageIcon('com.a');
      final defaultIcon = await app.getPackageIcon('');

      expect(fallback, isNotNull);
      expect(fallback, same(defaultIcon));
      expect(requested, ['com.a', '']);

      expect(await app.getPackageIcon('com.b'), same(defaultIcon));
      expect(requested, ['com.a', '', 'com.b']);
    },
  );

  test('caches a failed package icon lookup', () async {
    var iconCallCount = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async {
          iconCallCount++;
          throw PlatformException(code: 'unavailable');
        });

    final app = App();

    expect(await app.getPackageIcon('com.a'), isNull);
    expect(await app.getPackageIcon('com.a'), isNull);
    expect(await app.getPackageIcon(''), isNull);
    expect(iconCallCount, 2);
    expect(app.hasPackageIcon('com.a'), isTrue);
    expect(app.hasPackageIcon(''), isTrue);
  });

  test('uses false when crash detection is unavailable', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async {
          throw PlatformException(code: 'unavailable');
        });

    expect(await App().didCrashOnPreviousExecution(), isFalse);
  });

  test('reads the last process exit info from Android', () async {
    MethodCall? receivedCall;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          receivedCall = call;
          return <String, Object?>{
            'reason': 10,
            'timestamp': 1234,
            'description': 'user requested',
          };
        });

    final info = await App().getLastExitInfo();

    expect(receivedCall?.method, 'getLastExitInfo');
    expect(info?.reason, AppExitReason.userRequested);
    expect(info?.timestamp, 1234);
    expect(info?.description, 'user requested');
  });

  test('uses no exit info when Android cannot report one', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async => null);

    expect(await App().getLastExitInfo(), isNull);
  });

  test('uses no exit info when the platform call fails', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async {
          throw PlatformException(code: 'unavailable');
        });

    expect(await App().getLastExitInfo(), isNull);
  });

  test('forwards package change notices from Android', () async {
    var changes = 0;
    final app = App();
    app.onPackagesChanged = () => changes++;
    addTearDown(() => app.onPackagesChanged = null);

    await TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .handlePlatformMessage(
          channel.name,
          channel.codec.encodeMethodCall(const MethodCall('packagesChanged')),
          (_) {},
        );

    expect(changes, 1);
  });

  test('reports the installed apps permission Android answers with', () async {
    final methods = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          methods.add(call.method);
          return false;
        });

    expect(await App().isInstalledAppsPermissionGranted(), isFalse);
    expect(await App().requestInstalledAppsPermission(), isFalse);
    expect(methods, [
      'isInstalledAppsPermissionGranted',
      'requestInstalledAppsPermission',
    ]);
  });

  test(
    'treats a missing installed apps permission answer as granted',
    () async {
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (_) async => null);

      expect(await App().isInstalledAppsPermissionGranted(), isTrue);
      expect(await App().requestInstalledAppsPermission(), isFalse);
    },
  );
}
