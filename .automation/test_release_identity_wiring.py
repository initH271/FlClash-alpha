import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tool.release_identity import release_identity, verify_native_identity


class ReleaseIdentityWiringTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding='utf-8')

    def test_build_plan_uses_shared_identity_tag(self):
        source = self.read('.automation/build_plan.py')
        self.assertIn("release_identity(metadata)['tag']", source)
        self.assertNotIn("alpha-{metadata", source)

    def test_verify_apk_reads_version_name_and_reuses_shared_identity(self):
        source = self.read('.automation/verify_apk.py')
        self.assertIn('versionName=', source)
        self.assertIn('verify_native_identity', source)

    def test_bare_new_version_name_is_rejected(self):
        metadata = {'version': '0.8.98', 'upstreamVersion': '0.8.98',
                    'displayVersion': '0.8.98-alpha.13', 'revision': 13,
                    'build': 2026094013, 'applicationId': 'com.follow.clash.dev'}
        self.assertEqual(release_identity(metadata)['tag'], 'v0.8.98-alpha.13')
        with self.assertRaises(ValueError):
            verify_native_identity(metadata, 'com.follow.clash.dev', 2026094013, '0.8.98')
        with self.assertRaises(ValueError):
            verify_native_identity(metadata, 'com.follow.clash.dev', 2026094012, '0.8.98-alpha.13')
        verify_native_identity(metadata, 'com.follow.clash.dev', 2026094013, '0.8.98-alpha.13')

    def test_legacy_metadata_still_accepts_bare_version_name(self):
        legacy = {'version': '0.8.98', 'build': 2026094012,
                  'applicationId': 'com.follow.clash.dev'}
        self.assertEqual(release_identity(legacy)['tag'], 'alpha-0.8.98-2026094012')
        verify_native_identity(legacy, 'com.follow.clash.dev', 2026094012, '0.8.98')

    def test_prepare_release_passes_display_version(self):
        source = self.read('.github/scripts/prepare-release.py')
        self.assertIn("'--display-version', identity['displayVersion']", source)
        self.assertIn("metadata['tag'] = identity['tag']", source)

    def test_workflow_and_cnb_pass_build_name(self):
        for path in ('.github/workflows/build.yaml', '.cnb.yml'):
            source = self.read(path)
            self.assertIn('tool/release_identity.py --field displayVersion', source)
            self.assertIn('--build-name "$display_version"', source)


if __name__ == '__main__':
    unittest.main()
