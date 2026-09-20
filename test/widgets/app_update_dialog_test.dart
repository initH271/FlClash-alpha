import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:fl_clash/providers/app.dart';
import 'package:fl_clash/widgets/app_update_dialog.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Installer extends UpdateInstaller {
  int installs = 0;
  bool allowed = false;
  Future<String> Function()? callback;

  @override
  Future<bool> canInstall() async => allowed;

  @override
  Future<String> install(File file, Map<String, dynamic> release) async {
    installs++;
    return callback == null ? 'opened' : await callback!();
  }
}

class _Download extends UpdateDownload {
  final Completer<File> result = Completer<File>();
  CancelToken? token;

  _Download(UpdateInstaller installer)
    : super(installer: installer, transfer: (_, _, _, _) async {});

  @override
  Future<File> fetch(
    Map<String, dynamic> release,
    CancelToken token,
    ProgressCallback progress,
    void Function() verifying, {
    void Function(String)? onSource,
  }) {
    this.token = token;
    return result.future;
  }
}

void main() {
  const release = {
    'tag_name': 'alpha-test',
    'source': 'CNB',
    'body': 'Changes',
  };

  Future<void> pump(
    WidgetTester tester,
    _Installer installer,
    _Download download,
  ) async {
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [
          viewSizeProvider.overrideWithBuild((_, _) => const Size(800, 600)),
        ],
        locale: const Locale('en'),
        child: AppUpdateDialog(
          release: release,
          downloader: download,
          installer: installer,
        ),
      ),
    );
  }

  testWidgets(
    'downloads automatically but installation needs a tap and cannot duplicate',
    (tester) async {
      final installer = _Installer();
      final download = _Download(installer);
      await pump(tester, installer, download);
      expect(download.token, isNotNull);
      expect(find.text('Install update'), findsNothing);
      download.result.complete(File('verified.apk'));
      await tester.pump();
      expect(installer.installs, 0);
      final opened = Completer<String>();
      installer.callback = () => opened.future;
      await tester.tap(find.text('Install update'));
      await tester.pump();
      await tester.tap(find.text('Install update'));
      expect(installer.installs, 1);
      opened.complete('opened');
      await tester.pump();
      expect(
        find.text('The system installer is open. Confirm installation there.'),
        findsOneWidget,
      );
    },
  );

  testWidgets('disposing cancels a pending download without installing', (
    tester,
  ) async {
    final installer = _Installer();
    final download = _Download(installer);
    await pump(tester, installer, download);
    await tester.pumpWidget(const SizedBox());
    expect(download.token!.isCancelled, isTrue);
    download.result.complete(File('verified.apk'));
    await tester.pump();
    expect(installer.installs, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('permission return continues only after the user grants access', (
    tester,
  ) async {
    final installer = _Installer();
    installer.callback = () async =>
        installer.allowed ? 'opened' : 'permission';
    final download = _Download(installer);
    await pump(tester, installer, download);
    download.result.complete(File('verified.apk'));
    await tester.pump();
    await tester.tap(find.text('Install update'));
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(installer.installs, 1);
    installer.allowed = true;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    expect(installer.installs, 2);
  });
}
