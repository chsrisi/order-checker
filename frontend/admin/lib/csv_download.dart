import 'dart:typed_data';

import 'csv_download_io.dart'
    if (dart.library.js_interop) 'csv_download_web.dart'
    as impl;

/// Hands a downloaded CSV to the user. On the web (the only shipped admin target, delta
/// D2.1) this triggers a browser download; elsewhere it returns `false`.
bool saveCsv(String fileName, Uint8List bytes) => impl.saveCsv(fileName, bytes);
