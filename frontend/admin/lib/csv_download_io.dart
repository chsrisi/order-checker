import 'dart:typed_data';

/// The admin app ships for the web only; there is no file-save path on other platforms.
bool saveCsv(String fileName, Uint8List bytes) => false;
