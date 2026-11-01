import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:fl_clash/providers/app.dart';
import 'package:fl_clash/widgets/app_update_dialog.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers/test_app.dart';

class _Download extends UpdateDownload {
  _Download()
    : super(
        installer: const WindowsUpdateInstaller(),
        transfer: (_, _, _, _) async {},
      );

  @override
  Future<File> fetch(
    Map<String, dynamic> release,
    CancelToken token,
    ProgressCallback progress,
    void Function() verifying, {
    void Function(String)? onSource,
  }) async => File('release.exe');
}

class _Installer extends WindowsUpdateInstaller {
  int installs = 0;
  String result = 'cancelled';

  @override
  Future<String> install(File file, Map<String, dynamic> release) async {
    installs++;
    return result;
  }
}

void main() {
  testWidgets('declining the elevation leaves the install button ready', (
    tester,
  ) async {
    final installer = _Installer();
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [
          viewSizeProvider.overrideWithBuild((_, _) => const Size(800, 600)),
        ],
        locale: const Locale('en'),
        child: AppUpdateDialog(
          release: const {
            'tag_name': 'v0.9.2-alpha.22',
            'source': 'GitHub',
            'body': 'Changes',
            'publishedAt': '2026-11-02T10:00:00Z',
          },
          downloader: _Download(),
          installer: installer,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final install = find.widgetWithText(FilledButton, 'Install update');
    await tester.tap(install);
    await tester.pumpAndSettle();
    expect(installer.installs, 1);
    expect(tester.widget<FilledButton>(install).onPressed, isNotNull);
    expect(find.textContaining('installer'), findsNothing);

    installer.result = 'opened';
    await tester.tap(install);
    await tester.pumpAndSettle();
    expect(installer.installs, 2);
  });
}
