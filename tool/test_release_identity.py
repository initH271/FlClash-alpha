import unittest

from tool.release_identity import next_release, release_identity, verify_native_identity


class ReleaseIdentityTests(unittest.TestCase):
    def test_legacy_metadata_migrates_without_resetting_build(self):
        result = next_release({'version': '0.8.98', 'build': 2026094012,
                               'applicationId': 'com.follow.clash.dev'})
        self.assertEqual(result['build'], 2026094013)
        self.assertEqual(result['revision'], 13)
        self.assertEqual(result['displayVersion'], '0.8.98-alpha.13')
        self.assertEqual(result['applicationId'], 'com.follow.clash.dev')

    def test_upstream_upgrade_keeps_fork_revision_monotonic(self):
        result = next_release({'version': '0.8.98', 'upstreamVersion': '0.8.98',
                               'displayVersion': '0.8.98-alpha.13',
                               'revision': 13, 'build': 2026094013}, '0.8.99')
        self.assertEqual(result['version'], '0.8.99')
        self.assertEqual(result['displayVersion'], '0.8.99-alpha.14')
        self.assertEqual(result['build'], 2026094014)

    def test_invalid_or_mismatched_metadata_is_rejected(self):
        for extra in [{'build': True}, {'build': 2100000001}, {'revision': 0},
                      {'revision': 14}, {'upstreamVersion': '0.8.99'},
                      {'upstreamVersion': '0.8.98\nunsafe'},
                      {'displayVersion': '0.8.98-alpha.99'}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                release_identity(dict({'version': '0.8.98', 'build': 2026094013}, **extra))

    def test_legacy_and_readable_tags_follow_metadata_schema(self):
        identity = release_identity({'version': '0.8.98', 'build': 2026094013})
        self.assertEqual(identity['displayVersion'], '0.8.98-alpha.13')
        self.assertEqual(identity['tag'], 'alpha-0.8.98-2026094013')
        current = release_identity(next_release({'version': '0.8.98', 'build': 2026094012}))
        self.assertEqual(current['tag'], 'v0.8.98-alpha.13')

    def test_native_version_is_checked_without_breaking_legacy_apks(self):
        legacy = {'version': '0.8.98', 'build': 2026094012,
                  'applicationId': 'com.follow.clash.dev'}
        verify_native_identity(legacy, 'com.follow.clash.dev', 2026094012, '0.8.98')
        current = next_release(legacy)
        verify_native_identity(current, 'com.follow.clash.dev', 2026094013, '0.8.98-alpha.13')
        for package, build, name in [('com.follow.clash', 2026094013, '0.8.98-alpha.13'),
                                     ('com.follow.clash.dev', 2026094012, '0.8.98-alpha.13'),
                                     ('com.follow.clash.dev', 2026094013, '0.8.98')]:
            with self.subTest(package=package, build=build, name=name), self.assertRaises(ValueError):
                verify_native_identity(current, package, build, name)


if __name__ == '__main__':
    unittest.main()
