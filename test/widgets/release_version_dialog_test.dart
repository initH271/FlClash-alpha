import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:fl_clash/providers/app.dart';
import 'package:fl_clash/widgets/app_update_dialog.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _ReadyDownload extends UpdateDownload {
  _ReadyDownload()
    : super(
        installer: const UpdateInstaller(),
        transfer: (_, _, _, _) async {},
      );

  @override
  Future<File> fetch(
    Map<String, dynamic> release,
    CancelToken token,
    ProgressCallback progress,
    void Function() verifying, {
    void Function(String)? onSource,
  }) async => File('/tmp/unused-version-ui-fixture.apk');
}

void main() {
  testWidgets('update dialog presents the fork version and independent date', (
    tester,
  ) async {
    await tester.pumpWidget(
      TestApp(
        locale: const Locale('en'),
        overrides: [
          viewSizeProvider.overrideWithBuild((_, _) => const Size(800, 600)),
        ],
        child: AppUpdateDialog(
          release: const {
            'tag_name': 'v0.8.98-alpha.13',
            'displayVersion': '0.8.98-alpha.13',
            'build': 2026094013,
            'source': 'CNB',
            'body': '- Readable versions',
          },
          downloader: _ReadyDownload(),
          releaseDateLoader: () async => DateTime.utc(2026, 10, 6),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('0.8.98-alpha.13 · CNB'), findsOneWidget);
    expect(find.text('Release date: 2026-10-06'), findsOneWidget);
    expect(find.textContaining('2026094013'), findsNothing);
    expect(find.textContaining('Readable versions'), findsOneWidget);
  });
}
