import 'package:fl_clash/common/app_update.dart';

const primarySource = UpdateSource(
  name: 'primary',
  api: 'https://primary.test/latest/manifest.json',
  download: 'https://primary.test/download',
);
const mirrorSource = UpdateSource(
  name: 'mirror',
  api: 'https://mirror.test/latest/manifest.json',
  download: 'https://mirror.test/download',
);

/// The app ships one source, so only this copy reaches choice and fallback.
UpdateTarget mirrored(UpdateTarget target) => UpdateTarget(
  file: target.file,
  accepts: target.accepts,
  sources: const [primarySource, mirrorSource],
);
