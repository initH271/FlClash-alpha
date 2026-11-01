import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/database/database.dart' as db;
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/l10n/l10n.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/action.dart';
import 'package:fl_clash/providers/config.dart';
import 'package:fl_clash/providers/core.dart';
import 'package:fl_clash/providers/database.dart';
import 'package:fl_clash/state.dart';
import 'package:flutter/widgets.dart' show Locale;
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:riverpod/riverpod.dart';

import '../helpers/app_paths.dart';

class _MockCoreHandlerInterface extends Mock implements CoreHandlerInterface {}

class _ReadHook extends QueryInterceptor {
  Future<void> Function()? beforeRead;

  @override
  Future<List<Map<String, Object?>>> runSelect(
    QueryExecutor executor,
    String statement,
    List<Object?> args,
  ) async {
    await beforeRead?.call();
    return executor.runSelect(statement, args);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late db.Database testDatabase;
  late ProviderContainer container;
  late Map<String, int> requests;
  late _ReadHook reads;

  setUpAll(() => AppLocalizations.load(const Locale('en')));

  setUp(() {
    reads = _ReadHook();
    testDatabase = db.Database(NativeDatabase.memory().interceptWith(reads));
    db.database = testDatabase;
    requests = {};
    final core = _MockCoreHandlerInterface();
    when(() => core.updateGeoData(any())).thenAnswer((invocation) async {
      final name = invocation.positionalArguments.single as String;
      final count = requests[name] = (requests[name] ?? 0) + 1;
      return count == 1 ? '' : 'geo update already in progress';
    });
    container = ProviderContainer(
      overrides: [
        coreHandlerProvider.overrideWithValue(CoreController.scoped(core)),
      ],
    );
  });

  tearDown(() async {
    container.dispose();
    await testDatabase.close();
  });

  test(
    'an update all that overlaps one running skips what that one runs',
    () async {
      final action = container.read(resourcesActionProvider.notifier);

      final failures = await Future.wait([
        action.updateAll(),
        action.updateAll(),
      ]);

      expect(failures.expand((items) => items), isEmpty);
      expect(requests, {
        for (final geoResource in GeoResource.values) geoResource.name: 1,
      });
    },
  );

  group('a resource changed while its update waits or downloads', () {
    late HttpServer server;
    late Directory home;
    late Map<String, Completer<void>> held;
    late Map<String, Completer<void>> arrived;
    late List<String> requested;

    String urlOf(String path) => 'http://127.0.0.1:${server.port}/$path';

    String bodyOf(String path) => json.encode({
      'name': 'upstream',
      'icons': [
        {'name': '$path.png', 'url': 'https://example.com/$path.png'},
      ],
    });

    Completer<void> hold(String path) {
      arrived[path] = Completer();
      return held[path] = Completer();
    }

    setUp(() async {
      final bindingOverrides = HttpOverrides.current;
      HttpOverrides.global = null;
      addTearDown(() => HttpOverrides.global = bindingOverrides);
      globalState.packageInfo = PackageInfo(
        appName: 'FlClash',
        packageName: 'com.follow.clash',
        version: '1.0.0',
        buildNumber: '1',
      );
      globalState.container = container;
      home = await Directory.systemTemp.createTemp('resources_action_test');
      addTearDown(() => home.delete(recursive: true));
      await useAppPaths(home);
      held = {};
      arrived = {};
      requested = [];
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      addTearDown(() => server.close(force: true));
      server.listen((request) async {
        final path = request.uri.path.substring(1);
        requested.add(path);
        arrived[path]?.complete();
        await held[path]?.future;
        request.response.write(bodyOf(path));
        await request.response.close();
      });
      container.listen(iconSetsProvider, (_, _) {});
      container.listen(scriptsProvider, (_, _) {});
      await container.read(iconSetsProvider.future);
      await container.read(scriptsProvider.future);
      final config = container.read(patchClashConfigProvider);
      container.read(patchClashConfigProvider.notifier).value = config.copyWith(
        geoAutoUpdate: true,
      );
    });

    ResourcesAction resources() =>
        container.read(resourcesActionProvider.notifier);

    Future<void> gone(File file) async {
      final deadline = DateTime.now().add(const Duration(seconds: 10));
      while (await file.exists()) {
        if (DateTime.now().isAfter(deadline)) {
          fail('${file.path} still exists');
        }
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    }

    group('an icon set queued behind another', () {
      late IconSet second;
      late Completer<void> first;
      late Future<void> running;

      IconSets iconSets() => container.read(iconSetsProvider.notifier);

      Future<IconSet?> stored() async =>
          (await testDatabase.iconSetsDao.query().get())
              .where((item) => item.id == second.id)
              .firstOrNull;

      setUp(() async {
        second = IconSet(id: 2, name: 'Second', url: urlOf('second'));
        iconSets().put(IconSet(id: 1, name: 'First', url: urlOf('first')));
        iconSets().put(second);
        first = hold('first');
        running = resources().autoUpdate();
        await arrived['first']!.future;
      });

      test('keeps a name changed meanwhile and takes the icons', () async {
        iconSets().put(second.copyWith(name: 'Renamed'));

        first.complete();
        await running;

        final iconSet = (await stored())!;
        expect(iconSet.name, 'Renamed');
        expect(iconSet.icons.single.name, 'second.png');
      });

      test('downloads and keeps a url the options moved it to', () async {
        await container
            .read(iconSetsActionProvider.notifier)
            .sync(second, url: urlOf('moved'));

        first.complete();
        await running;

        final iconSet = (await stored())!;
        expect(iconSet.url, urlOf('moved'));
        expect(iconSet.icons.single.name, 'moved.png');
        expect(requested, isNot(contains('second')));
      });

      test('is not downloaded or put back once deleted', () async {
        iconSets().del(second.id);

        first.complete();
        await running;

        expect(await stored(), isNull);
        expect(requested, isNot(contains('second')));
      });
    });

    group('a script', () {
      late Script first;
      late Script second;

      Scripts scripts() => container.read(scriptsProvider.notifier);

      ScriptsAction action() => container.read(scriptsActionProvider.notifier);

      Future<List<Script>> stored() => testDatabase.scriptsDao.query().get();

      setUp(() async {
        first = Script(
          id: 1,
          label: 'First',
          url: urlOf('first'),
          lastUpdateTime: DateTime(2020),
        );
        second = Script(
          id: 2,
          label: 'Second',
          url: urlOf('second'),
          lastUpdateTime: DateTime(2020),
        );
        scripts().put(first);
        scripts().put(second);
      });

      Future<void> autoUpdateHeldAtFirst(
        FutureOr<void> Function() meanwhile,
      ) async {
        final gate = hold('first');
        final running = resources().autoUpdate();
        await arrived['first']!.future;
        await meanwhile();
        gate.complete();
        await running;
      }

      group('queued behind another', () {
        test('keeps a name changed meanwhile and takes the content', () async {
          await autoUpdateHeldAtFirst(() {
            scripts().put(second.copyWith(label: 'Renamed'));
          });

          expect((await stored()).get(second.id)!.label, 'Renamed');
          expect(
            await File(await second.path).readAsString(),
            bodyOf('second'),
          );
        });

        test('downloads and keeps a url the dialog moved it to', () async {
          await autoUpdateHeldAtFirst(
            () => action().updateScript(second, url: urlOf('moved')),
          );

          expect((await stored()).get(second.id)!.url, urlOf('moved'));
          expect(await File(await second.path).readAsString(), bodyOf('moved'));
          expect(requested, isNot(contains('second')));
        });

        test('keeps the order set meanwhile', () async {
          await autoUpdateHeldAtFirst(() => scripts().order(1, 0));

          expect((await stored()).map((item) => item.label), [
            'Second',
            'First',
          ]);
        });

        test('is not downloaded or put back once deleted', () async {
          await autoUpdateHeldAtFirst(() => scripts().del(second.id));

          expect((await stored()).get(second.id), isNull);
          expect(requested, isNot(contains('second')));
          await gone(File(await second.path));
        });
      });

      group('downloading', () {
        test('keeps a name changed meanwhile and takes the content', () async {
          await autoUpdateHeldAtFirst(() {
            scripts().put(first.copyWith(label: 'Renamed'));
          });

          final script = (await stored()).get(first.id)!;
          expect(script.label, 'Renamed');
          expect(script.lastUpdateTime.isAfter(DateTime(2020)), isTrue);
          expect(await File(await first.path).readAsString(), bodyOf('first'));
        });

        test('replaces content edited meanwhile, as any update does', () async {
          await autoUpdateHeldAtFirst(() async {
            final edited = await first.copyWith(label: 'Edited').save('edited');
            action().putScript(edited);
          });

          expect((await stored()).get(first.id)!.label, 'Edited');
          expect(await File(await first.path).readAsString(), bodyOf('first'));
        });

        test('gives way to a url the dialog moved it to', () async {
          await autoUpdateHeldAtFirst(
            () => action().updateScript(first, url: urlOf('moved')),
          );

          expect((await stored()).get(first.id)!.url, urlOf('moved'));
          expect(await File(await first.path).readAsString(), bodyOf('moved'));
        });

        test('leaves no row or file when deleted', () async {
          await autoUpdateHeldAtFirst(() => scripts().del(first.id));

          expect((await stored()).get(first.id), isNull);
          await gone(File(await first.path));
        });

        test('clears its file when deleted as the file is written', () async {
          final file = File(await first.path);
          var removed = false;
          reads.beforeRead = () async {
            if (!removed && await file.exists()) {
              removed = true;
              await testDatabase.scripts.remove((t) => t.id.equals(first.id));
            }
          };

          await resources().updateScript(first);

          expect(removed, isTrue);
          expect((await stored()).get(first.id), isNull);
          await gone(file);
        });
      });

      test('a new url lands after an update of the old one', () async {
        final moved = hold('moved');
        final moving = action().updateScript(first, url: urlOf('moved'));
        await arrived['moved']!.future;

        await resources().updateScript(first);
        moved.complete();
        await moving;

        expect((await stored()).get(first.id)!.url, urlOf('moved'));
        expect(await File(await first.path).readAsString(), bodyOf('moved'));
      });

      test('a failed download leaves the row and the file alone', () async {
        await File(await first.path).create(recursive: true);
        await File(await first.path).writeAsString('kept');
        final moved = urlOf('moved');
        final original = urlOf('first');
        await server.close(force: true);

        await expectLater(
          action().updateScript(first, url: moved),
          throwsA(anything),
        );

        final script = (await stored()).get(first.id)!;
        expect(script.url, original);
        expect(await File(await first.path).readAsString(), 'kept');
      });
    });

    test('an update all keeps what changed as it listed the rows', () async {
      final iconSets = container.read(iconSetsProvider.notifier);
      final scripts = container.read(scriptsProvider.notifier);
      final renamedSet = IconSet(id: 1, name: 'Set', url: urlOf('set'));
      final movedSet = IconSet(id: 2, name: 'Moved', url: urlOf('old-set'));
      final renamed = Script(
        id: 1,
        label: 'Script',
        url: urlOf('script'),
        lastUpdateTime: DateTime(2020),
      );
      final moved = Script(
        id: 2,
        label: 'Moved',
        url: urlOf('old-script'),
        lastUpdateTime: DateTime(2020),
      );
      iconSets.put(renamedSet);
      iconSets.put(movedSet);
      scripts.put(renamed);
      scripts.put(moved);
      await pumpEventQueue();

      final running = resources().updateAll();
      iconSets.put(renamedSet.copyWith(name: 'Renamed'));
      iconSets.put(movedSet.copyWith(url: urlOf('new-set')));
      scripts.put(renamed.copyWith(label: 'Renamed'));
      scripts.put(moved.copyWith(url: urlOf('new-script')));

      expect(await running, isEmpty);

      final sets = await testDatabase.iconSetsDao.query().get();
      expect(sets.map((item) => item.name), ['Renamed', 'Moved']);
      expect(sets.last.url, urlOf('new-set'));
      expect(sets.last.icons.single.name, 'new-set.png');
      final rows = await testDatabase.scriptsDao.query().get();
      expect(rows.map((item) => item.label), ['Renamed', 'Moved']);
      expect(rows.last.url, urlOf('new-script'));
      expect(await File(await moved.path).readAsString(), bodyOf('new-script'));
    });
  });
}
