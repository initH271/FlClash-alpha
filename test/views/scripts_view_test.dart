import 'package:fl_clash/l10n/l10n.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/config/scripts.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers/context_menu.dart';
import '../helpers/test_app.dart';
import '../helpers/test_database_providers.dart';

class _RecordingScriptsAction extends ScriptsAction {
  final updated = <({Script script, String? url})>[];

  @override
  Future<void> updateScript(Script script, {String? url}) async {
    updated.add((script: script, url: url));
  }
}

void main() {
  setUpAll(() => AppLocalizations.load(const Locale('en')));

  testWidgets('sync asks for no new url and the url dialog hands one over', (
    tester,
  ) async {
    final script = Script(
      id: 1,
      label: 'alpha',
      url: 'https://example.com/old.js',
      lastUpdateTime: DateTime(2026),
    );
    final action = _RecordingScriptsAction();
    final container = ProviderContainer(
      overrides: [
        scriptsProvider.overrideWith(() => TestScripts([script])),
        scriptsActionProvider.overrideWith(() => action),
      ],
    );
    addTearDown(container.dispose);
    globalState.container = container;
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const TestApp(child: ScriptsView()),
      ),
    );
    await tester.pumpAndSettle();

    await rightClick(tester, find.text('alpha'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sync'));
    await tester.pumpAndSettle();

    await rightClick(tester, find.text('alpha'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('URL'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byType(TextField),
      'https://example.com/new.js',
    );
    await tester.tap(find.text('Submit'));
    await tester.pumpAndSettle();

    expect(action.updated, [
      (script: script, url: null),
      (script: script, url: 'https://example.com/new.js'),
    ]);
  });
}
