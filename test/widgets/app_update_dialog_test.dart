import 'dart:async';
import 'dart:convert';
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
    _Download download, {
    String body = 'Changes',
  }) async {
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [
          viewSizeProvider.overrideWithBuild((_, _) => const Size(800, 600)),
        ],
        locale: const Locale('en'),
        child: AppUpdateDialog(
          release: {...release, 'body': body},
          downloader: download,
          installer: installer,
        ),
      ),
    );
  }

  testWidgets('long notes start compact and can expand and collapse', (
    tester,
  ) async {
    final installer = _Installer();
    final download = _Download(installer);
    final body = List.generate(20, (index) => '- Change $index').join('\n');
    await pump(
      tester,
      installer,
      download,
      body: '$body\n<!-- flclash-update ${jsonEncode({'notes': body})} -->',
    );
    final notes = find.byKey(const ValueKey('update-release-notes'));
    expect(tester.widget<Text>(notes).maxLines, 6);
    expect(tester.widget<Text>(notes).data, body);
    expect(find.text('Expand'), findsOneWidget);
    await tester.tap(find.text('Expand'));
    await tester.pump();
    expect(tester.widget<Text>(notes).maxLines, isNull);
    expect(tester.widget<Text>(notes).data, contains('Change 19'));
    await tester.ensureVisible(find.text('Collapse'));
    await tester.tap(find.text('Collapse'));
    await tester.pump();
    expect(tester.widget<Text>(notes).maxLines, 6);
    expect(download.token!.isCancelled, isFalse);
    expect(installer.installs, 0);
  });

  testWidgets(
    'structured notes show readable groups without JSON or metadata',
    (tester) async {
      final installer = _Installer();
      final download = _Download(installer);
      final payload = jsonEncode({
        'schemaVersion': 2,
        'versions': [
          {
            'version': 'test',
            'tag': 'alpha-test',
            'groups': [
              {
                'type': 'breaking',
                'entries': [
                  {'id': 'a', 'text': 'Re-import backups'},
                ],
              },
              {
                'version': 'old',
                'tag': 'alpha-old',
                'groups': [
                  {
                    'type': 'feat',
                    'entries': [
                      {'id': 'old', 'text': 'Old released feature'},
                    ],
                  },
                ],
              },
              {
                'type': 'feat',
                'entries': [
                  {'id': 'b', 'text': 'New dashboard'},
                ],
              },
            ],
          },
        ],
      });
      await pump(
        tester,
        installer,
        download,
        body: 'Download table\n<!-- flclash:changelog:json\n$payload\n-->',
      );
      final notes = tester.widget<Text>(
        find.byKey(const ValueKey('update-release-notes')),
      );
      expect(notes.data, contains('Breaking changes\n• Re-import backups'));
      expect(notes.data, contains('New features\n• New dashboard'));
      expect(notes.data, isNot(contains('schemaVersion')));
      expect(notes.data, isNot(contains('Download table')));
      expect(notes.data, isNot(contains('Old released feature')));
      expect(find.text('Expand'), findsNothing);
    },
  );

  testWidgets('legacy notes hide comments and retain the marked content', (
    tester,
  ) async {
    final installer = _Installer();
    final download = _Download(installer);
    await pump(
      tester,
      installer,
      download,
      body:
          'Download table\n<!-- flclash:changelog:begin -->\n'
          '- Fix crashes\n<!-- internal build metadata -->\n'
          '<!-- flclash:changelog:end -->\nChecksums',
    );
    final notes = tester.widget<Text>(
      find.byKey(const ValueKey('update-release-notes')),
    );
    expect(notes.data, '- Fix crashes');
    expect(find.text('Expand'), findsNothing);
    await pump(tester, installer, download, body: '');
    expect(find.byKey(const ValueKey('update-release-notes')), findsNothing);
  });

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
