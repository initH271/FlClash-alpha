import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../../tool/src/release_notes/range.dart';

void main() {
  test(
    'readable version retains the legacy tag as the incremental baseline',
    () {
      final repo = Directory.systemTemp.createTempSync(
        'release-version-notes-',
      );
      addTearDown(() => repo.deleteSync(recursive: true));
      void git(List<String> args) {
        final result = Process.runSync(
          'git',
          args,
          workingDirectory: repo.path,
          environment: const {
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_CONFIG_SYSTEM': '/dev/null',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': 'Version fixture',
            'GIT_AUTHOR_EMAIL': 'version@example.test',
            'GIT_COMMITTER_NAME': 'Version fixture',
            'GIT_COMMITTER_EMAIL': 'version@example.test',
          },
        );
        expect(result.exitCode, 0, reason: result.stderr.toString());
      }

      git(['init', '--quiet', '--initial-branch=main']);
      git(['commit', '--allow-empty', '-m', 'feat: old feature']);
      git(['tag', 'alpha-0.8.98-2026094012']);
      git([
        'commit',
        '--allow-empty',
        '-m',
        'feat(version): readable versions\n\nChangelog: Readable fork versions',
      ]);
      final result = AlphaReleaseNotes.generate(
        root: repo.path,
        version: '0.8.98',
        displayVersion: '0.8.98-alpha.13',
        build: 2026094013,
      );
      final visible = result.notes.replaceAll(RegExp(r'<!--[\s\S]*?-->'), '');
      expect(result.baseTag, 'alpha-0.8.98-2026094012');
      expect(visible, contains('FlClash-alpha 0.8.98-alpha.13'));
      expect(visible, contains('Readable fork versions'));
      expect(visible, isNot(contains('old feature')));
      expect(visible, isNot(contains('2026094013')));
      git(['tag', 'v0.8.98-alpha.13']);
      git([
        'commit',
        '--allow-empty',
        '-m',
        'fix(version): next release\n\nChangelog: Next release only',
      ]);
      final next = AlphaReleaseNotes.generate(
        root: repo.path,
        version: '0.8.98',
        displayVersion: '0.8.98-alpha.14',
        build: 2026094014,
      );
      expect(next.baseTag, 'v0.8.98-alpha.13');
      expect(next.notes, contains('Next release only'));
      expect(next.notes, isNot(contains('Readable fork versions')));
      expect(
        () => AlphaReleaseNotes.generate(
          root: repo.path,
          version: '0.8.98',
          displayVersion: '0.8.99-alpha.13',
          build: 2026094013,
        ),
        throwsArgumentError,
      );
    },
  );
}
