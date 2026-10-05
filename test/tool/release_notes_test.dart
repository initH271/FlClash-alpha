import 'dart:io';

import 'package:test/test.dart';

void main() {
  late Directory repo;
  final script = File('.github/scripts/release_notes.py').absolute;

  setUpAll(() {
    if (!script.existsSync()) {
      fail('release notes script not found at ${script.path}');
    }
  });

  void runGit(List<String> arguments, {int? expectExitCode}) {
    final result = Process.runSync(
      'git',
      arguments,
      workingDirectory: repo.path,
      environment: const {
        // The fixture is isolated from the machine's identity and signing
        // configuration, so tagging or committing here can never inherit a
        // GPG key or a global user identity the tests do not control.
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_AUTHOR_NAME': 'Notes test',
        'GIT_AUTHOR_EMAIL': 'notes-test@example.com',
        'GIT_COMMITTER_NAME': 'Notes test',
        'GIT_COMMITTER_EMAIL': 'notes-test@example.com',
        'GIT_AUTHOR_DATE': '2026-01-02T00:00:00Z',
        'GIT_COMMITTER_DATE': '2026-01-02T00:00:00Z',
      },
    );
    if (expectExitCode != null) {
      expect(result.exitCode, expectExitCode, reason: result.stderr.toString());
      return;
    }
    if (result.exitCode != 0) {
      fail('git ${arguments.join(' ')} failed: ${result.stderr}');
    }
  }

  void commit(String message) {
    runGit(['commit', '--allow-empty', '--quiet', '--message', message]);
  }

  void tag(String name) {
    runGit(['tag', name]);
  }

  ({String stdout, String stderr, int exitCode}) generate({
    required String version,
    required int build,
    String? base,
    int expectedExitCode = 0,
  }) {
    final result = Process.runSync(
      'python3',
      [
        script.path,
        '--repo',
        repo.path,
        '--version',
        version,
        '--build',
        '$build',
        if (base != null) ...['--base', base],
      ],
      environment: const {
        'GIT_CONFIG_GLOBAL': '/dev/null',
        'GIT_CONFIG_SYSTEM': '/dev/null',
      },
    );
    expect(
      result.exitCode,
      expectedExitCode,
      reason: 'stdout=${result.stdout} stderr=${result.stderr}',
    );
    return (
      stdout: '${result.stdout}',
      stderr: '${result.stderr}',
      exitCode: result.exitCode,
    );
  }

  setUp(() {
    repo = Directory.systemTemp.createTempSync('flclash-notes-');
    runGit(['init', '--quiet', '--initial-branch=main']);
    commit('chore: initial commit');
  });

  tearDown(() {
    repo.deleteSync(recursive: true);
  });

  test('two consecutive releases each show only their own range', () {
    commit('feat: first feature\n\nChangelog: Added the first feature');
    tag('alpha-0.8.98-2026094001');

    commit('fix: second fix\n\nChangelog: Fixed the second thing');
    tag('alpha-0.8.98-2026094002');

    commit('perf: third change\n\nChangelog: Sped up the third path');
    tag('alpha-0.8.98-2026094003');

    final second = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(second, contains('构建 2026094002'));
    expect(second, contains('Fixed the second thing'));
    expect(second, isNot(contains('Added the first feature')));

    final third = generate(version: '0.8.98', build: 2026094003).stdout;
    expect(third, contains('Sped up the third path'));
    expect(third, isNot(contains('Fixed the second thing')));
    expect(third, isNot(contains('Added the first feature')));
  });

  test('old features already in the base are excluded', () {
    commit(
      'feat: ship the Bettbox home widgets\n\nChangelog: Bettbox home widgets',
    );
    tag('alpha-0.8.98-2026094009');
    commit('fix(ui): polish the header\n\nChangelog: Polished the header');

    final notes = generate(version: '0.8.98', build: 2026094010).stdout;
    expect(notes, contains('Polished the header'));
    expect(notes, isNot(contains('Bettbox')));
  });

  test('reports the base tag, base sha and source sha', () {
    commit('feat: feature\n\nChangelog: A feature');
    tag('alpha-0.8.98-2026094001');
    final baseSha = Process.runSync('git', [
      'rev-parse',
      'HEAD',
    ], workingDirectory: repo.path).stdout.toString().trim();

    commit('fix: fix\n\nChangelog: A fix');
    final sourceSha = Process.runSync('git', [
      'rev-parse',
      'HEAD',
    ], workingDirectory: repo.path).stdout.toString().trim();

    final result = generate(version: '0.8.98', build: 2026094002);
    final stderr = result.stderr;
    expect(
      stderr,
      contains('alpha-0.8.98-2026094001 ($baseSha) -> $sourceSha'),
    );
  });

  test('Changelog skip is excluded while merge wrappers stay silent', () {
    commit('feat: real feature\n\nChangelog: Kept feature');
    commit('chore: internal\n\nChangelog: skip');
    tag('alpha-0.8.98-2026094001');
    commit('fix: hidden\n\nChangelog: skip');

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('本版没有用户可见的变化。'));
    expect(notes, isNot(contains('hidden')));
  });

  test('merge commits do not duplicate their branch commits', () {
    commit('feat: branched feature\n\nChangelog: Branched feature');
    tag('alpha-0.8.98-2026094001');
    runGit(['checkout', '--quiet', '-b', 'work']);
    commit('fix: branch fix\n\nChangelog: Branch fix');
    runGit(['checkout', '--quiet', 'main']);
    commit('chore: main moves on');
    runGit(['merge', '--quiet', '--no-ff', '--no-edit', 'work']);

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(RegExp('Branch fix').allMatches(notes).length, 1);
    expect(notes, isNot(contains('Merge branch')));
  });

  test('a rewritten merge keeps the changelog text of its merge commit', () {
    commit('feat: seed');
    tag('alpha-0.8.98-2026094001');
    runGit(['checkout', '--quiet', '-b', 'work']);
    // The branch commit lost its trailer to a rewrite, so only the merge
    // commit still carries the text the previous release must not repeat.
    commit('feat: rewritten subject');
    runGit(['checkout', '--quiet', 'main']);
    commit('chore: main moves on');
    runGit([
      'merge',
      '--quiet',
      '--no-ff',
      '--no-edit',
      '--message',
      'Merge pull request #7 from work\n\nChangelog: Text that survived the rewrite\n',
      'work',
    ]);

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('Text that survived the rewrite'));
  });

  test('the Changelog trailer outranks the commit subject', () {
    commit(
      'feat: subject that nobody should read\n\nChangelog: Trailer text wins',
    );
    tag('alpha-0.8.98-2026094001');
    commit('fix: another subject\n\nChangelog: Trailer wins again');

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('Trailer wins again'));
    expect(notes, isNot(contains('another subject')));
  });

  test('only feat, fix, perf, revert and breaking entries are collected', () {
    commit('feat: feature');
    tag('alpha-0.8.98-2026094001');
    commit('docs: forgotten docs');
    commit('chore: forgotten chore');
    commit('ci: forgotten ci');
    commit('test: forgotten test');
    commit('refactor: forgotten refactor');
    commit('fix: kept fix');
    commit('perf: kept perf');
    commit('revert: kept revert');

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('Kept fix'));
    expect(notes, contains('Kept perf'));
    expect(notes, contains('Kept revert'));
    expect(notes, isNot(contains('Forgotten')));
  });

  test('a Changelog-Type override moves an entry between sections', () {
    commit('feat: seed');
    tag('alpha-0.8.98-2026094001');
    commit(
      'fix: looks like a fix\n\nChangelog-Type: perf\nChangelog: Really a speedup',
    );

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('### Performance'));
    expect(notes, contains('Really a speedup'));
    expect(notes, isNot(contains('### Fixes')));
  });

  test('a breaking change is listed in its own section', () {
    commit('feat: seed');
    tag('alpha-0.8.98-2026094001');
    commit(
      'feat(core)!: drop the legacy flag\n\nBREAKING CHANGE: The legacy flag is gone',
    );

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, contains('### Breaking'));
    expect(notes, contains('The legacy flag is gone'));
  });

  test('duplicate texts collapse to one line', () {
    commit('feat: seed');
    tag('alpha-0.8.98-2026094001');
    commit('fix: same text');
    commit('fix: same text');

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(RegExp('Same text').allMatches(notes).length, 1);
  });

  test('unreachable, future, beta and stable tags are ignored', () {
    commit('feat: base feature\n\nChangelog: Base feature');
    tag('alpha-0.8.98-2026094001');

    runGit(['checkout', '--quiet', '-b', 'side']);
    commit('feat: side feature\n\nChangelog: Side feature');
    tag('alpha-0.8.98-2026094002');
    commit('feat: side future\n\nChangelog: Side future');
    tag('alpha-0.8.98-2026094099');
    runGit(['checkout', '--quiet', 'main']);

    tag('v0.8.98');
    tag('alpha-0.8.98-2026094010-beta');
    tag('beta-0.8.98-2026094050');
    tag('random-tag');

    final result = generate(version: '0.8.98', build: 2026094005);
    expect(result.stderr, contains('notes base alpha-0.8.98-2026094001'));
    expect(result.stdout, isNot(contains('Side feature')));
  });

  test('a future build tag does not become the base', () {
    commit('feat: older\n\nChangelog: Older feature');
    tag('alpha-0.8.98-2026094001');
    commit('feat: newer\n\nChangelog: Never published');
    tag('alpha-0.8.98-2026094300');

    final result = generate(version: '0.8.98', build: 2026094002);
    expect(result.stderr, contains('alpha-0.8.98-2026094001'));
  });

  test('the base uses the largest reachable build below this one', () {
    commit('feat: a\n\nChangelog: A');
    tag('alpha-0.8.98-2026094001');
    commit('feat: b\n\nChangelog: B');
    tag('alpha-0.8.98-2026094002');
    commit('feat: c\n\nChangelog: C');
    tag('alpha-0.8.98-2026094004');

    final result = generate(version: '0.8.98', build: 2026094007);
    expect(result.stderr, contains('alpha-0.8.98-2026094004'));
    expect(result.stdout, isNot(contains('C\n')));
  });

  test('an explicit base is honoured and checked', () {
    commit('feat: a\n\nChangelog: A');
    tag('alpha-0.8.98-2026094001');
    commit('feat: b\n\nChangelog: B');
    tag('alpha-0.8.98-2026094002');
    commit('feat: c\n\nChangelog: C');

    final result = generate(
      version: '0.8.98',
      build: 2026094005,
      base: 'alpha-0.8.98-2026094001',
    );
    expect(result.stderr, contains('alpha-0.8.98-2026094001'));
    expect(result.stdout, contains('B'));
    expect(result.stdout, contains('C'));
  });

  test('an illegal or missing base fails without falling back', () {
    commit('feat: a\n\nChangelog: A');
    tag('alpha-0.8.98-2026094001');
    commit('feat: b\n\nChangelog: B');

    final notATag = generate(
      version: '0.8.98',
      build: 2026094002,
      base: 'v0.8.98',
      expectedExitCode: 1,
    );
    expect(notATag.stdout, isEmpty);

    final tooNew = generate(
      version: '0.8.98',
      build: 2026094001,
      base: 'alpha-0.8.98-2026094001',
      expectedExitCode: 1,
    );
    expect(tooNew.stderr, contains('not smaller'));

    final missing = generate(
      version: '0.8.98',
      build: 2026094002,
      base: 'alpha-0.8.98-2026094099',
      expectedExitCode: 1,
    );
    expect(missing.stderr, contains('does not exist'));
  });

  test('an explicit base on another lineage fails', () {
    commit('feat: a\n\nChangelog: A');
    runGit(['checkout', '--quiet', '-b', 'side']);
    commit('feat: only on side\n\nChangelog: Only on side');
    tag('alpha-0.8.98-2026094100');
    runGit(['checkout', '--quiet', 'main']);
    commit('feat: b\n\nChangelog: B');

    final result = generate(
      version: '0.8.98',
      build: 2026094101,
      base: 'alpha-0.8.98-2026094100',
      expectedExitCode: 1,
    );
    expect(result.stderr, contains('not reachable'));
  });

  test('without any reachable base the run fails instead of using history', () {
    commit('feat: only feature\n\nChangelog: Only feature');

    final result = generate(
      version: '0.8.98',
      build: 2026094002,
      expectedExitCode: 1,
    );
    expect(result.stdout, isEmpty);
    expect(result.stderr, contains('refusing to fall back'));
  });

  test('an empty range still reports the version header', () {
    commit('feat: seed');
    tag('alpha-0.8.98-2026094001');

    final notes = generate(version: '0.8.98', build: 2026094002).stdout;
    expect(notes, startsWith('FlClash-alpha 0.8.98（构建 2026094002）'));
    expect(notes, contains('本版没有用户可见的变化。'));
  });
}
