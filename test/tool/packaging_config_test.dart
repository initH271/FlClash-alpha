import 'dart:io';

import 'package:fl_clash/common/app_update.dart';
import 'package:fl_clash/common/launch.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

void main() {
  group('Windows identity', () {
    final config =
        loadYaml(
              File('windows/packaging/exe/make_config.yaml').readAsStringSync(),
            )
            as YamlMap;
    final script = File(
      'windows/packaging/exe/inno_setup.iss',
    ).readAsStringSync();
    final runner = File('windows/runner/Runner.rc').readAsStringSync();

    test('the installer is the one the updater accepts', () {
      expect(config['app_id'], windowsApplicationId);
      expect(config['publisher_name'], 'initH271');
      expect(config['install_dir_name'], r'{autopf64}\FlClash-alpha');
    });

    test('uninstalling removes the data folder the runner names', () {
      final company = RegExp(
        r'VALUE "CompanyName", "([^"]+)"',
      ).firstMatch(runner)![1]!;
      final product = RegExp(
        r'VALUE "ProductName", "([^"]+)"',
      ).firstMatch(runner)![1]!;
      expect(company, 'com.follow.dev');
      expect(script, contains('{userappdata}\\$company\\$product'));
      expect(script, contains('{localappdata}\\$company\\$product'));
      expect(script, isNot(contains(r'\com.follow\')));
    });

    test('the installer removes the startup entry the app writes', () {
      expect(script, contains("Run', '$windowsAutoLaunchName'"));
      expect(script, isNot(contains('APP_NAME')));
    });

    test('the shortcuts do not share a path with the official app', () {
      final icons = RegExp(r'Name: "\{(autoprograms|autodesktop)\}[^"]*"');
      final names = icons.allMatches(script).map((match) => match[0]!).toList();
      expect(names, hasLength(2));
      expect(names, everyElement(endsWith(r'\\FlClash-alpha"')));
    });

    test('nothing ends a process by name alone', () {
      expect(script, isNot(contains('taskkill')));
      expect(script, contains(r'$_.Path.StartsWith($d'));
    });

    test('the updater asks for the relaunch the installer offers', () {
      expect(windowsInstallerArguments, contains('/RELAUNCH'));
      expect(script, contains("'/RELAUNCH'"));
    });
  });

  group('Linux packaging teardown', () {
    for (final format in ['deb', 'rpm']) {
      test('$format removes the Helper unit only on a real uninstall', () {
        final config =
            loadYaml(
                  File(
                    'linux/packaging/$format/make_config.yaml',
                  ).readAsStringSync(),
                )
                as YamlMap;
        final scripts = (config['postuninstall_scripts'] as YamlList)
            .cast<String>();

        expect(scripts.first, contains('exit 0'));
        expect(
          scripts,
          contains('rm -f /etc/systemd/system/flclash-helper.service'),
        );
        expect(
          scripts.any((script) => script.contains('systemctl daemon-reload')),
          isTrue,
        );
      });
    }
  });

  test('every Linux package names the GTK application id as its window '
      'class', () {
    final applicationId = RegExp(
      r'set\(APPLICATION_ID "([^"]+)"\)',
    ).firstMatch(File('linux/CMakeLists.txt').readAsStringSync())!.group(1);

    for (final format in ['deb', 'rpm', 'appimage']) {
      final config =
          loadYaml(
                File(
                  'linux/packaging/$format/make_config.yaml',
                ).readAsStringSync(),
              )
              as YamlMap;
      expect(config['startup_wm_class'], applicationId, reason: format);
    }
  });

  test('rpm keeps the Core bytes the Helper was built against', () {
    final config =
        loadYaml(
              File('linux/packaging/rpm/make_config.yaml').readAsStringSync(),
            )
            as YamlMap;
    final macros = (config['spec_macros'] as YamlList).cast<String>();

    expect(macros, contains('%global debug_package %{nil}'));
    expect(macros, contains('%global __os_install_post %{nil}'));
  });
}
