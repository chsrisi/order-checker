import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Saves [bytes] through a temporary Blob URL and a hidden `<a download>`.
bool saveCsv(String fileName, Uint8List bytes) {
  final blob = web.Blob(
    <JSAny>[bytes.toJS].toJS,
    web.BlobPropertyBag(type: 'text/csv;charset=utf-8'),
  );
  final url = web.URL.createObjectURL(blob);
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = fileName
    ..style.display = 'none';
  web.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  // Some browsers start the download asynchronously; revoke the URL a little later.
  Timer(const Duration(seconds: 30), () => web.URL.revokeObjectURL(url));
  return true;
}
