import 'dart:convert';
import 'dart:io';

import 'package:fl_clash/common/changelog.dart' as app;
import 'package:fl_clash/common/package.dart' as package;
import 'package:test/test.dart';

import '../../tool/src/changelog/models.dart';
import '../../tool/src/release_notes/manual.dart';
import '../../tool/src/release_notes/range.dart';

const _tun = 'VPN 重启后不再自己绕自己，流量终于学会出门了';

const _section =
    '备注不生效。\n\n'
    '## 0.8.98\n\n'
    '### 修好了\n'
    '- $_tun\n\n'
    '### 新玩意儿\n'
    '- 日志留几天，现在你说了算\n';

void main() {
  group('generate', () {
    late Directory repo;

    void git(List<String> arguments) {
      final result = Process.runSync(
        'git',
        arguments,
        workingDirectory: repo.path,
        environment: const {
          'GIT_CONFIG_GLOBAL': '/dev/null',
          'GIT_CONFIG_SYSTEM': '/dev/null',
          'GIT_CONFIG_NOSYSTEM': '1',
          'GIT_AUTHOR_NAME': 'Notes test',
          'GIT_AUTHOR_EMAIL': 'notes-test@example.com',
          'GIT_COMMITTER_NAME': 'Notes test',
          'GIT_COMMITTER_EMAIL': 'notes-test@example.com',
        },
      );
      expect(result.exitCode, 0, reason: result.stderr.toString());
    }

    void commitNotes(String content) {
      File('${repo.path}/.github/release-notes.md')
        ..createSync(recursive: true)
        ..writeAsStringSync(content);
      git(['add', '.github/release-notes.md']);
      git(['commit', '--quiet', '-m', 'chore(release): prepare notes']);
    }

    AlphaReleaseNotes run() => AlphaReleaseNotes.generate(
      root: repo.path,
      version: '0.8.98',
      build: 2026094002,
    );

    setUp(() {
      repo = Directory.systemTemp.createTempSync('flclash-manual-notes-');
      git(['init', '--quiet', '--initial-branch=main']);
      git(['commit', '--allow-empty', '--quiet', '-m', 'feat: seed']);
      git(['tag', 'alpha-0.8.98-2026094001']);
      git([
        'commit',
        '--allow-empty',
        '--quiet',
        '-m',
        'fix(core): protect sockets\n\nChangelog: Stop looping back',
      ]);
    });

    tearDown(() => repo.deleteSync(recursive: true));

    test('a section replaces generated entries in Markdown and JSON', () {
      commitNotes(_section);

      final result = run();

      expect(result.notes, isNot(contains('Stop looping back')));
      expect(result.notes, contains('### 修好了\n- $_tun\n'));
      expect(result.notes, contains('### 新玩意儿\n'));
      expect(result.notes, isNot(contains('备注不生效')));
      final version = app.parseReleaseChangelog(result.notes)!;
      expect(version.groups.map((group) => group.type.name), ['feat', 'fix']);
      expect(version.groups.last.entries.single.text, _tun);
      expect(package.parseReleaseBody(result.notes), contains(_tun));
      expect(result.warnings.single, contains('hand written section'));
    });

    test('without a section the generated entries stay', () {
      commitNotes('跟随上游 v0.9.2，保留滚动日志。\n');

      final result = run();

      expect(result.notes, contains('Stop looping back'));
      expect(result.warnings, isNot(anyElement(contains('release-notes.md'))));
    });

    test('a missing file also falls back to generated entries', () {
      expect(run().notes, contains('Stop looping back'));
    });

    test('a section for another version warns and falls back', () {
      commitNotes(_section.replaceFirst('0.8.98', '0.8.97'));

      final result = run();

      expect(result.notes, contains('Stop looping back'));
      expect(result.notes, isNot(contains(_tun)));
      expect(result.warnings, anyElement(contains('0.8.97')));
    });

    test('a malformed section stops the release', () {
      commitNotes('## 0.8.98\n\n### Fixes\n- $_tun\n');

      expect(run, throwsFormatException);
    });

    test('reads the file from the source commit, not the working tree', () {
      commitNotes('跟随上游。\n');
      File('${repo.path}/.github/release-notes.md').writeAsStringSync(_section);

      expect(run().notes, contains('Stop looping back'));
    });
  });

  group('parseManualNotes', () {
    List<ChangelogGroup>? parse(String source) =>
        parseManualNotes(source, '0.8.98').groups;

    test('accepts a v prefix and CRLF line endings', () {
      final groups = parse('## v0.8.98\r\n### 修好了\r\n- 好了\r\n');

      expect(groups!.single.type, ChangelogType.fix);
      expect(groups.single.entries.single.text, '好了');
    });

    test('stops at the next version heading', () {
      final groups = parse('## 0.8.98\n### 修好了\n- 新的\n## 0.8.97\n乱写\n');

      expect(groups!.single.entries.single.text, '新的');
    });

    test('warns about bullets with no version heading', () {
      final notes = parseManualNotes('- 忘了写标题\n', '0.8.98');

      expect(notes.groups, isNull);
      expect(notes.warnings.single, contains('no "## 0.8.98" heading'));
    });

    for (final (name, section) in const [
      ('an unknown group', '### Fixes\n- 好了\n'),
      ('a bullet outside a group', '- 好了\n'),
      ('stray text', '### 修好了\n好了\n'),
      ('another bullet marker', '### 修好了\n* 好了\n'),
      ('an empty group', '### 修好了\n### 更快了\n- 快了\n'),
      ('a repeated group', '### 修好了\n- 好了\n### 修好了\n- 又好了\n'),
      ('an empty section', '\n'),
      ('an empty bullet', '### 修好了\n- \n'),
      ('a comment that could close the payload', '### 修好了\n- 好 --> 了\n'),
      ('a repeated section', '### 修好了\n- 好了\n## 0.8.98\n'),
    ]) {
      test('rejects $name', () {
        expect(() => parse('## 0.8.98\n$section'), throwsFormatException);
      });
    }

    test('the committed notes file parses for the committed version', () {
      final release =
          jsonDecode(File('.github/release.json').readAsStringSync())
              as Map<String, dynamic>;

      expect(
        () => parseManualNotes(
          File(manualNotesPath).readAsStringSync(),
          release['displayVersion'] as String,
        ),
        returnsNormally,
      );
    });
  });
}
